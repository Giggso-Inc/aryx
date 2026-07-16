# API Flow: POST /ask (CPQ Guided-Configuration Mode)

**Module:** `src/aryx/api/ask_api.py :: _run_cpq_turn()`
**Engine:** `src/aryx/cpq/engine.py :: CpqEngine`
**Rule evaluator:** `src/aryx/cpq/bml.py :: BmlEvaluator`
**Session shape:** `src/aryx/cpq/state.py :: CpqSession`, `ConfigAttr`

## What this document is

`/ask` is one endpoint that serves two very different jobs. If the question
is a plain knowledge-graph lookup, it answers like a normal Q&A bot (not
covered here — see `ask_api.py`'s non-CPQ path). If the question is about
**configuring and quoting a product** (an XML-ingested BigMachines/Oracle
CPQ catalog — e.g. "Quote APX Next for a US customer"), it switches into
**CPQ mode**, and every following turn of that same conversation stays in
CPQ mode until the quote is submitted or abandoned.

This document covers CPQ mode only: `_run_cpq_turn()`.

## The big idea, in plain English

Think of this like a smart order form that a salesperson fills out with a
customer over a chat, one field at a time:

1. First it asks two things it absolutely cannot proceed without: **which
   product**, and **which country**.
2. Then it loads that product's whole list of configurable fields (its
   "attributes") from the database.
3. For every field, it tries to fill it in **automatically** — from
   something the customer already said, from a sensible default, or
   because a business rule makes the answer obvious. Only if none of that
   works does it actually ask the customer.
4. It asks about ONE remaining field at a time, waits for the answer, locks
   it in, and re-runs step 3 (because answering one field can change which
   other fields are even relevant — this is called "cascading").
5. Once every field is resolved, it shows a plain-English summary and waits
   for the customer to say "confirm" before generating the final order
   (the "BOM payload") — it will **never** show or submit a payload
   built from guessed values.

Everything the server needs to remember between turns (which product, what
country, what's been answered so far, etc.) is packed into a `session_data`
object and handed back to the client — the client sends it back on the
next request. There's no server-side session store; the whole conversation
state round-trips in the HTTP payload every turn.

---

## Complete Flow Diagram — one turn, start to finish

```
CLIENT
  │
  │  POST /ask
  │  Body: { question: "...", workspace_id: 1, session_data: {...} }
  │
  ▼
╔══════════════════════════════════════════════════════════════════════╗
║  0. SESSION RESTORE                                                  ║
║                                                                      ║
║  • session_data.mode == "cpq"?  → rehydrate CpqSession from it       ║
║    else                          → brand-new CpqSession()            ║
║  • First turn ever for this session → mint session.run_id (a UUID,   ║
║    stays the same for every future turn — lets you trace one whole   ║
║    quote's lifecycle across many HTTP requests in the logs)          ║
║  • session.turn += 1                                                 ║
╚══════════════════════════════════════════════════════════════════════╝
  │
  ▼
╔══════════════════════════════════════════════════════════════════════╗
║  0b. PENDING PRODUCT-SWITCH CONFIRMATION (only if last turn asked)   ║
║                                                                      ║
║  If the PREVIOUS turn detected the customer naming a DIFFERENT       ║
║  product mid-quote and asked "switch and discard current config?"   ║
║  — this turn's raw text IS that yes/no answer, not a new question.   ║
║    "yes" → wipe all filled answers, reset to the new product,        ║
║            fall through to re-anchor country for it                  ║
║    "no"  → keep current product, answer "OK, continuing with X",     ║
║            STOP HERE (early return)                                  ║
╚══════════════════════════════════════════════════════════════════════╝
  │  (falls through only on "yes", or if this gate wasn't pending)
  ▼
╔══════════════════════════════════════════════════════════════════════╗
║  STEP 1 — SEQUENTIAL ANCHOR GATE                                     ║
║  "Anchors" = the two facts the engine refuses to guess: product      ║
║  family and country. Asked one at a time, never together.            ║
║                                                                      ║
║  1a. PRODUCT not yet known?                                          ║
║      • Try to detect a product mention in the question, matched     ║
║        against the REAL product/family names actually ingested in   ║
║        this workspace (never a hardcoded list)                      ║
║      • If this turn is a direct reply to "which product?" — accept   ║
║        the raw text as the answer                                   ║
║      • Still nothing? Try resolving it against real catalog/option   ║
║        data (handles names outside the simple pattern match)        ║
║      • Still nothing? ASK: "I need the product family (e.g. X, Y)." ║
║        STOP HERE (early return) — nothing below runs until answered ║
║                                                                      ║
║  1b. PRODUCT already known — check for a SWITCH                     ║
║      • Re-scan this turn's text for a mention of a DIFFERENT real    ║
║        product than the one this session is already configuring     ║
║      • Found one? Don't switch silently — ASK "switch to X and       ║
║        discard the current config? (yes/no)" and STOP HERE           ║
║        (this is the gate that step 0b answers on the NEXT turn)      ║
║                                                                      ║
║  1c. COUNTRY not yet known?                                          ║
║      • ASK: "what's the destination country?" STOP HERE              ║
║      • (Product must be resolved BEFORE country is ever asked —      ║
║        strictly sequential, never both at once)                     ║
╚══════════════════════════════════════════════════════════════════════╝
  │  (only reached once BOTH product and country are known)
  ▼
╔══════════════════════════════════════════════════════════════════════╗
║  STEP 2 — LOAD THE PRODUCT'S CONFIGURATION ATTRIBUTES                ║
║                                                                      ║
║  • load_product_config(reader, workspace_id, product_name)           ║
║    → every "ConfigAttr" (configurable field) ingested for this       ║
║      product's catalog, with its menu options, default value,       ║
║      required flag, hidden flag, native source ids                  ║
║  • No attrs came back at all? → return {} (not a CPQ product;        ║
║    the request falls through to the plain knowledge-graph Q&A path) ║
║  • catalog_prefix is derived from the loaded attrs (scopes every     ║
║    rule/function lookup below to just THIS product's own catalog —  ║
║    a workspace can hold several ingested catalogs at once, and       ║
║    native BigMachines ids collide across them)                      ║
║  • Scan the question AGAIN, now that real option text is loaded,     ║
║    for hints the earlier generic scan couldn't catch (e.g. a         ║
║    specific battery type or carry-solution name)                    ║
║  • Load this catalog's three rule families, needed by every step     ║
║    below:                                                            ║
║      - hiding_rules          (can make a field disappear entirely)  ║
║      - rec_rules / con_rules (can suggest or restrict a value)      ║
║      - bml_eval               (runs any script-backed rule logic)   ║
╚══════════════════════════════════════════════════════════════════════╝
  │
  ▼
┌─ Is the quote already fully configured and awaiting the customer's ─┐
│  final "confirm"? (session.status == "awaiting_approval")           │
└───────────────────────────────┬───────────────────────────────────┬─┘
                    YES ────────┘                         NO ───────┘
                    │                                              │
                    ▼                                              ▼
    ╔═══════════════════════════════════╗          (continue to STEP 3 below)
    ║  REVIEW-STAGE ROUTER               ║
    ║  (checked in this exact order —    ║
    ║  each one "wins" over the next)    ║
    ║                                    ║
    ║  a. "show me the json" request?    ║
    ║     → STEP 8-PREVIEW: render the   ║
    ║       current payload as a labeled ║
    ║       PREVIEW (never final,        ║
    ║       cpq_payload stays empty)     ║
    ║                                    ║
    ║  b. Explicit approval phrase       ║
    ║     ("confirm", "yes", "looks      ║
    ║     good", "submit", ...)?         ║
    ║     → STEP 8-FINAL: status=        ║
    ║       "approved", build the REAL   ║
    ║       BOM payload, return it as    ║
    ║       cpq_payload                  ║
    ║                                    ║
    ║  c. A genuine question, not an     ║
    ║     answer ("what does X mean?")?  ║
    ║     → STEP 7: answer it from the   ║
    ║       graph, then re-show review   ║
    ║                                    ║
    ║  d. Wants to CHANGE something      ║
    ║     already answered?              ║
    ║     → STEP 6: hand off to the      ║
    ║       CASCADE flow (see below)     ║
    ║                                    ║
    ║  e. None of the above matched      ║
    ║     → gently re-show the summary,  ║
    ║       remind them how to confirm   ║
    ║       or ask for JSON              ║
    ╚═══════════════════════════════════╝
                    │
                    ▼
              (return response; wait for next turn)
```

### The main configuring loop (when NOT yet awaiting approval)

```
╔══════════════════════════════════════════════════════════════════════╗
║  §A — DETECT SPECIAL REQUESTS BEFORE TREATING THIS AS AN ANSWER       ║
║                                                                      ║
║  Checked in this order, because a plain-English message like "show  ║
║  me the json so far" or "what does Region mean?" must never be       ║
║  mistaken for an invalid menu answer:                                ║
║                                                                      ║
║  1. mode_request = detect_response_mode_request(question)            ║
║     → "json" (wants a preview), "batch" (wants ALL pending           ║
║       questions at once), or None (normal one-at-a-time flow)        ║
║  2. "what values are available for X?" → answer directly with that   ║
║     field's option list, re-prioritize X to the front of the         ║
║     pending queue, STOP HERE                                        ║
║  3. If there's already a pending question AND this isn't turn 1 AND  ║
║     no mode_request fired: is this a genuine Q&A question about the  ║
║     field just asked (not an attempt to answer it)? → STEP 7,        ║
║     answer it, then re-ask the same pending field next turn          ║
╚══════════════════════════════════════════════════════════════════════╝
  │
  ▼
╔══════════════════════════════════════════════════════════════════════╗
║  STEP 5 — LOCK IN THE ANSWER TO LAST TURN'S QUESTION                 ║
║  (skipped on turn 1 — there's nothing pending yet)                   ║
║                                                                      ║
║  1. Take session.pending_variables[0] — the ONE field we asked       ║
║     about last turn                                                  ║
║  2. Recompute which of its menu options are still valid right now    ║
║     (a constraint rule may have narrowed them since we asked)        ║
║  3. Try to match this turn's raw text against a real option for      ║
║     that field (customer may have typed the exact option name)       ║
║  4. No match on raw text? Fall back to the earlier NL-hint extraction║
║  5. Matched → store the value:                                       ║
║       - "multi" select fields → append to a list (checkbox-style)    ║
║       - everything else       → overwrite the single value           ║
║     Also tag HOW it was filled ("user") and, if this field is a       ║
║     decision-required type (country/region-shaped), copy the same    ║
║     value onto any sibling field that shares that concept and has    ║
║     no options of its own yet                                        ║
║  6. No match at all, and the field HAS real options → don't guess:   ║
║     re-show the same question with its option list and STOP HERE     ║
╚══════════════════════════════════════════════════════════════════════╝
  │
  ▼
╔══════════════════════════════════════════════════════════════════════╗
║  STEP 3 — THE RULE-EVALUATION LOOP (hide → fill → recommend →        ║
║  constrain, repeated until nothing changes, capped at 8 passes)      ║
║                                                                      ║
║  Runs once per turn, on the CURRENT full set of answers-so-far.      ║
║  Each pass, in this exact order:                                     ║
║                                                                      ║
║   1. HIDE — apply every hiding rule. A field whose condition says    ║
║      "hide this" disappears from the visible set. If a field that    ║
║      WAS visible just got hidden, its stored answer is discarded     ║
║      too (it's no longer a real, user-facing decision)              ║
║   2. AUTO-FILL — for every still-visible, still-empty field, try in  ║
║      order: (a) something the customer already said (a "hint"),      ║
║      (b) the field's own default value from the source data,         ║
║      (c) if a business rule already governs this field AND exactly   ║
║      one valid option remains, pick it automatically — no real        ║
║      decision to make, (d) otherwise, if the field has 2+ real        ║
║      options and nothing above resolved it, leave it EMPTY and       ║
║      queue it to be asked — the engine never blindly guesses a       ║
║      real decision                                                   ║
║   3. RECOMMEND — apply recommendation rules: "if field A = X, set     ║
║      field B to Y" — fills in more fields automatically              ║
║   4. CONSTRAIN — apply constraint rules: narrows which options are    ║
║      still valid for a field, given everything answered so far        ║
║      (doesn't fill anything, just shrinks the menu for later steps)  ║
║                                                                      ║
║   Repeat all 4 sub-steps until BOTH the set of filled fields AND     ║
║   the set of visible fields stop changing between passes (or 8       ║
║   passes have run — a safety cap, real catalogs stabilize well        ║
║   before that).                                                      ║
║                                                                      ║
║   Result: visible_attrs (what's left to potentially ask about),      ║
║   filled (every value resolved so far), display_filled (the same     ║
║   values in human-readable form), constrained_opts (narrowed menus)  ║
╚══════════════════════════════════════════════════════════════════════╝
  │
  ▼
╔══════════════════════════════════════════════════════════════════════╗
║  Determine what's STILL genuinely pending                            ║
║                                                                      ║
║  governed_ids = fields a rule actually targets, OR fields explicitly ║
║                 marked "not required" in the source data             ║
║  Re-run auto_fill ONE more time with that governed set — this is     ║
║  what actually decides the final "pending" list for THIS turn        ║
╚══════════════════════════════════════════════════════════════════════╝
  │
  ▼
┌───────────────────────┬─────────────────────────┬────────────────────┐
│  pending is EMPTY      │  pending non-empty AND   │  pending non-empty  │
│                        │  turn >= MAX_TURNS cap   │  (normal case)      │
└───────────┬───────────┴─────────────┬───────────┴──────────┬─────────┘
            ▼                         ▼                      ▼
╔═════════════════════╗   ╔═══════════════════════╗  ╔═══════════════════╗
║ STEP 6 — FORMAT B     ║   ║ TURN-CAP SAFETY VALVE  ║  ║ Explicit request?  ║
║ (completion)          ║   ║                        ║  ║                    ║
║                       ║   ║ NEVER fabricate a      ║  ║ "json" → STEP      ║
║ status =              ║   ║ finished BOM here.     ║  ║   8-PREVIEW render ║
║ "awaiting_approval"   ║   ║ Explicitly tell the    ║  ║ "batch" → show      ║
║                       ║   ║ customer the config    ║  ║   EVERY pending    ║
║ Show a plain-English  ║   ║ is INCOMPLETE, list    ║  ║   question at once ║
║ summary of every      ║   ║ what's still missing,  ║  ║ neither → STEP 4    ║
║ decision made. NEVER  ║   ║ and keep asking the    ║  ║   FORMAT A: ask     ║
║ show the raw JSON     ║   ║ next pending field —   ║  ║   about JUST the    ║
║ here — only on        ║   ║ the conversation stays ║  ║   next ONE pending  ║
║ explicit request      ║   ║ open, it just won't    ║  ║   field, with a     ║
║ (Step 8-preview)       ║   ║ silently "finish"      ║  ║   short context     ║
║ or "confirm" (Step 8-  ║   ║                        ║  ║   sentence and its  ║
║ final)                 ║   ║                        ║  ║   real option list  ║
╚═════════════════════╝   ╚═══════════════════════╝  ╚═══════════════════╝
            │                         │                      │
            └─────────────────────────┴──────────────────────┘
                                       │
                                       ▼
╔══════════════════════════════════════════════════════════════════════╗
║  RETURN — every branch converges here                                ║
║                                                                      ║
║  {                                                                   ║
║    answer: "<the text above>",                                      ║
║    session_data: session.to_dict(),   ← client MUST echo this back   ║
║    cpq_payload: <only set on STEP 8-FINAL approval, else null>,      ║
║    preview: true only when this turn rendered a JSON preview          ║
║  }                                                                    ║
║  Also persisted to conversation history for audit/replay.            ║
╚══════════════════════════════════════════════════════════════════════╝
```

---

## The CASCADE branch (Step 6 — customer changes an already-answered field)

Triggered from the review-stage router (§d above) whenever the customer's
message is recognized as wanting to CHANGE a value already locked in
(e.g. "actually, make it the Enhanced hardware version instead").

```
╔══════════════════════════════════════════════════════════════════════╗
║  _handle_cascade()                                                    ║
║                                                                      ║
║  1. Find every OTHER field that DEPENDS on the field being changed    ║
║     (anything a hiding/recommendation/constraint rule connects to it)║
║  2. ERASE the changed field's old value AND every dependent field's   ║
║     value — they're now stale, not just "maybe still fine"           ║
║  3. Parse and lock in the NEW value for the changed field itself       ║
║     (same option-matching logic as Step 5)                           ║
║     • couldn't parse it? ask for clarification with the real option  ║
║       list and STOP HERE                                              ║
║  4. Re-run the EXACT SAME Step-3 rule-evaluation loop (hide → fill →  ║
║     recommend → constrain) on this now-partially-erased state — this  ║
║     is what re-derives the dependent fields' new, correct values      ║
║  5. Log every value that actually changed (old → new, which rule      ║
║     caused it, which turn) into session.cascade_log — an audit trail ║
║     of "why does the quote look like this now"                       ║
║  6. Re-show the review summary (same shape as Step 6 completion,      ║
║     above), now reflecting the cascaded state                        ║
╚══════════════════════════════════════════════════════════════════════╝
```

**Plain English:** changing one answer doesn't just overwrite that one
field — it correctly un-decides everything that answer used to influence,
then lets the same automatic rule logic re-decide all of it fresh, instead
of leaving stale, now-wrong values sitting in the quote.

## The Q&A branch (Step 7 — answering a real question mid-configuration)

Triggered whenever the customer's message reads as a genuine question
("what's the difference between X and Y?") rather than an attempt to
answer the pending field or change a prior one.

```
╔══════════════════════════════════════════════════════════════════════╗
║  _handle_cpq_qa()                                                     ║
║                                                                      ║
║  1. Answer the question using the normal knowledge-graph Q&A         ║
║     machinery (same retrieval the non-CPQ /ask path uses)             ║
║  2. Configuration state is untouched — nothing is filled, nothing     ║
║     is erased                                                        ║
║  3. If resume_review is true (question came in DURING the final       ║
║     review stage) → re-show the review summary right after the       ║
║     answer, so the customer lands back where they were                ║
║  4. Otherwise (question came in mid-configuration) → after the        ║
║     answer, re-show the SAME pending question that was waiting        ║
║     before the customer asked — nothing was skipped                   ║
╚══════════════════════════════════════════════════════════════════════╝
```

---

## Why some things are deliberately NOT automatic

- **The engine will never guess a real decision.** If a field has 2 or
  more valid options and nothing (hint, default, or rule) resolves it,
  it goes to the customer — even if that means more turns. This is a
  hard design rule ("Stop and Wait"), not an oversight.
- **JSON/the final BOM is never shown unasked**, not even once the
  configuration is fully complete. The customer always sees a
  plain-English summary first; the raw payload is opt-in (preview) or
  gated behind an explicit "confirm" (final).
- **The turn cap never fabricates a finished order.** If the conversation
  runs long and fields are still unresolved when the cap is hit, the
  answer explicitly says so and keeps asking — it does not pretend to be
  done.
- **Product and country are asked one at a time, never together**, and
  never guessed from unrelated text — confirmed by a real regression this
  session where a bare reply like "US" (answering the country anchor
  question) was almost silently misread as a NEW product name.

## Known current limitation (see `docs/CPQ_MULTI_CATALOG_ASK_FLOW_BUGS_PLAN.md`)

`productSelectionProduct_all` is now treated as decision-required (always
asked, never blind-guessed) specifically because it's a shared, catalog-wide
option list with no rule reliably narrowing it to the resolved product —
without this, "first eligible option by order" could silently pick an
unrelated product family's code. This is a targeted exception, not a
general pattern — see that doc for the full incident this fixed.
