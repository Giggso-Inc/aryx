# CPQ Post-Quote Q&A and Configuration Editing — Plan

**Status:** Implemented (D1-D4) and live-verified against a real APX Next
Enhanced quote (workspace 14) — see §8 for 2 real bugs the live
verification pass found and fixed, both in this plan's own new code.
**Date:** 2026-07-23
**Depends on:** `docs/CPQ_CASCADE_CONVERSATION_PLAN.md` (the base
conversational-flow spec — Steps 1-8) — this plan extends STEP 6/7/8, it
does not replace them.

---

## 1. Problem statement (client language)

> After the CPQ engine generates the Quote JSON, the client should still
> be able to ask questions about the quote — what a particular attribute
> is set to, what values are available for it — and change any
> configuration inside it. If the client wants to remove an attribute or
> add a new one, that should also work correctly.

## 2. Current state, verified against the actual code

Everything the client is asking for **already exists today — but only
while `session.status == "awaiting_approval"`**, i.e. *before* the client
says "confirm" (`ask_api.py:2141` gates STEP 6/7/8 routing on exactly
this status):

- **Q&A about a specific attribute's value/availability** — STEP 7,
  `_handle_cpq_qa` + `detect_attr_query` (fast path, no LLM: answers
  straight from `attr.options` already in memory).
- **Change a value** — STEP 6, `_handle_cascade`/`_handle_cascade_multi`
  (single- and multi-attribute changes in one message), plus bulk
  grid-quantity updates (`detect_bulk_quantity_change`).
- **Remove an attribute** — `detect_multi_select_removal`, but **scoped
  to optional multi-select items only** (e.g. deselecting one mount from
  a grid). No removal path exists for single-select or required attrs.
- **Add an attribute** — **no precedent exists anywhere in the engine.**

**The actual gap:** once the client says "confirm",
`session.status = "approved"`, `session.complete = True`, the JSON is
returned — and **that status is never checked again anywhere in
`ask_api.py`.** The next message falls through to the generic top-of-turn
path with no awareness it's now editing an already-generated quote. This
is undefined/accidental behavior today, not a built feature — confirmed
by grepping every `session.status ==` check in the file.

## 3. Resolved decisions (HITL, this session)

**D1 — Post-confirm session state.** Confirming does **not** lock the
quote. The same session stays live for further Q&A/edits; each accepted
change regenerates and re-shows the JSON. No new "reopen"/"amend" intent
is needed. `session.status` gains one new value, `"post_approval"`, set
alongside `session.complete = True` at STEP 8 (replacing the dead-end
`"approved"` value) so routing can distinguish "first time showing this
JSON" from "editing an already-shown one" without changing the client-
facing behavior described above.

**D2 — "Add an attribute" scope.** Only attributes that already exist in
the ingested catalog, are **`required == False`** (optional or
multi-select — checked regardless of which source pool below produced
the candidate), and are **currently excluded from this quote's
payload** are addable — never an invented/ad-hoc field, and never a
required one even if it happens to be technically absent from the
payload right now. Three concrete sources of "excluded but real,"
each still gated by the `required == False` filter:
1. An optional multi-select the client previously declined
   (`display_filled[vn] == "(none)"`, `filled_source == "user"`).
2. An attr dropped by `payload_flow_exclusions()`/
   `resolve_always_ask_skips()` (flow-exclusion guesses — e.g. a
   model-context mirror on a product-driven flow). **Excluded from this
   plan if `required == True`** — a required attr in this state means
   the flow logic determined it doesn't apply to the active flow at
   all, which is a stronger statement than "hidden but optional," and
   re-adding it is out of scope here.
3. A hidden-rule-excluded attr (`apply_hiding_rules`) whose hiding
   condition is no longer true given the CURRENT filled state (a genuine
   "this became relevant again" case, not a bypass of the rule) —
   **and** `required == False`.

Never invents a `variable_name` or option that doesn't exist in
`ConfigAttr`/`MenuOption` data — this is additive activation of real,
optional catalog data, not free-form payload editing.

**Hard invariant (elevated from a risk note — applies to BOTH D2 and
D3):** every add/remove decision is re-checked against the CURRENTLY
ACTIVE rule set at the moment of the request, never a cached/stale
exclusion snapshot. `detect_attr_activation`/`_handle_attr_activation`
call `apply_hiding_rules`/`apply_constraint_rules` fresh against
`session.filled` before allowing an add; `_handle_multi_select_removal`
(already does this today) continues re-validating against active
constraints after removal. An attribute whose hiding condition is
CURRENTLY true is never addable, full stop — this is not a bypass
mechanism for the rule engine.

**D3 — "Remove an attribute" scope.** Stays scoped to
`required == False` optional/multi-select items only, exactly like
today's `detect_multi_select_removal` — **never extended to required
attributes**, symmetric with D2. A required attribute can be CHANGED
(STEP 6, already works) but never removed outright, since the
downstream BOM/CPQ API's payload contract almost certainly depends on
every required field being present (confirmed precedent: `build_payload`
already treats `required`/`hidden`/`set_type` as structural, not
optional, throughout the engine).

**D4 — Nullify an optional SINGLE-select attribute's current value.**
D3 as designed only covers multi-select removal
(`detect_multi_select_removal`) — it has no mechanism for clearing a
single-select attribute back to blank once it holds a real value (today
you can only CHANGE it to a different option, never unset it). New,
narrower capability, gated the same way as D2/D3:

1. **`required == False` only** — a required attribute can never be
   nulled, same reasoning as D3 (the payload contract needs it present).
2. **Live rule-check, not just a static flag:** allowed ONLY if the
   attribute is NOT currently held to its value by a still-active rule.
   Concretely: if `filled_source[vn] == "rule"` (set by a
   recommendation/constraint) AND that rule's condition still evaluates
   true against `session.filled`, clearing is refused — the very next
   STEP 3 pass would just re-derive the exact same value, making the
   "clear" a silent no-op at best and a rule violation at worst if the
   engine didn't re-derive it. If the value was `"rule"`-sourced but that
   rule's condition NO LONGER holds (same live-check discipline as D2
   case 3), clearing is allowed.
3. **Needs a genuine "stays empty" state, not just a pop from `filled`**
   — popping a key from `filled` alone isn't enough: `auto_fill`'s
   existing fallback chain (hint → default → rule → blind first-by-order)
   would immediately re-fill SOME value for it on the very next pass,
   since nothing today represents "the user deliberately wants this
   blank" for a single-select attr. Multi-select already has exactly
   this concept — an empty `filled_multi[vn]` tagged
   `filled_source[vn] == "user"` renders as `"(none)"` and is never
   re-guessed (`auto_fill`'s existing multi-select branch). D4 reuses
   the identical convention for single-select: `filled[vn] = ""` +
   `filled_source[vn] == "user"` is a new, explicit "deliberately
   cleared" marker `auto_fill`'s single-select branch must check for
   (mirroring the multi-select check almost line-for-line) and respect,
   not fill through.

## 4. Design

### 4.1 New routing block: `session.status == "post_approval"`

Mirrors the existing `"awaiting_approval"` block (`ask_api.py:2141`)
almost exactly — same STEP 6/7/8 machinery, reused as-is where possible:

```python
if session.status in ("awaiting_approval", "post_approval", "approved"):
    ...  # existing STEP 6/7/8 body, unchanged
```

Rather than duplicating ~700 lines, widen the existing `if` condition to
cover both statuses. The only behavioral fork needed is at STEP 8
(`detect_approval`): saying "confirm" again while already
`"post_approval"` just re-shows the current JSON (idempotent), it does
not need to re-run anything new.

**Backward-compat guard:** `"approved"` (today's dead-end value) stays a
valid alias in the widened condition, permanently — a session confirmed
*before* this ships and still held by a client (e.g. echoed back from a
browser that hasn't refreshed) must keep routing correctly, not silently
fall through to the generic top-of-turn path. The FIRST action inside the
widened block normalizes it: `if session.status == "approved":
session.status = "post_approval"` — so every session converges to the
one real status going forward, and nothing downstream needs to know the
legacy value ever existed.

**Regression-audit requirement:** every sub-branch already inside the
`"awaiting_approval"` block (pending collision, pending anchor variants,
etc.), not just the 3 paths this plan adds, must be reviewed for sane
post-confirmation behavior before this ships — widening the condition
exposes all of them at once, not just STEP 6/7/8.

### 4.2 New: attribute-activation detector (`detect_attr_activation`)

New method on `CpqEngine`, mirroring `detect_multi_select_removal`'s
shape: takes the question text + the 3 candidate pools from D2 above,
matches via the same `_label_mentioned` fuzzy matcher every other
change-request detector already uses (no new NLP surface). Returns the
matched attr + (for hiding-rule-excluded candidates) confirmation that
its hiding condition no longer holds against `session.filled`.

**`attr.hidden` guard:** the candidate pool for D2 case 3 (hiding-rule-
excluded) must explicitly exclude any `ConfigAttr` with `attr.hidden ==
True`. This is a DIFFERENT flag from "currently hidden by an active
rule" — `attr.hidden` is BM's own permanent "never show this in any UI"
marker (source XML `hidden=1`), unrelated to rule state and never
meant to be surfaced to a customer at all, regardless of what any rule's
condition currently evaluates to. Conflating the two would let
`detect_attr_activation` "add back" a field the real native UI never
shows under any circumstance — a correctness bug, not just a UX one.

Wired into the `"post_approval"`-widened routing block, same priority
position as `detect_multi_select_removal` today (before the generic
collision/change-request checks, since "add X" and "change X" are
distinct intents needing to be told apart before either fires).

### 4.3 `_handle_attr_activation()` (new, mirrors `_handle_multi_select_removal`)

1. For a declined optional multi-select: same path as answering it fresh
   — apply the newly-stated option(s), re-run STEP 3's rule loop.
2. For a flow-exclusion/hiding-rule-excluded attr: clear it from
   `_hidden_for_payload`'s equivalent for this turn, add to `pending` so
   it's asked like a normal question (reuses `next_question_prompt`),
   THEN re-run STEP 3. Never silently guesses the newly-activated attr's
   value.
3. Cascade note explains what happened ("Added **Extended Warranty** to
   your quote — what value would you like?"), same phrasing convention
   `_handle_cascade` already uses.

### 4.4 Removal path — no new code needed

`detect_multi_select_removal`/`_handle_multi_select_removal` already do
exactly what D3 scopes this to. The only change is routing: they become
reachable from `"post_approval"` too, via the widened `if` in §4.1 — no
new detector, no new handler.

### 4.4b New: nullify detector for single-select attrs (`detect_attr_clear`)

D4 needs genuinely new code, unlike removal (§4.4). New `CpqEngine`
method, same fuzzy `_label_mentioned` matcher as every other detector:

1. Matches clear-verb phrasing ("clear X", "unset X", "make X blank",
   "remove the value from X") against a SINGLE-select, `required==False`
   attr that currently holds a real value in `filled`.
2. Rejects (returns `None`) if `required == True` — same gate as
   D2/D3, checked first, cheapest.
3. Rejects if `filled_source.get(vn) == "rule"` AND the governing
   recommendation/constraint rule's condition still evaluates true
   against current `session.filled` — the live re-check from D4 point 2.
   Reuses the same rule-lookup machinery `apply_recommendation_rules`/
   `apply_constraint_rules` already expose (via `_attr_index`), not new
   evaluation logic.
4. On match: `_handle_attr_clear()` (new, mirrors `_handle_cascade`'s
   shape) sets `filled[vn] = ""`, `filled_source[vn] = "user"`,
   `display_filled[vn] = "(none)"`, invalidates and re-evaluates
   dependents exactly like any other change (§4.5's cascade guarantee
   applies here too — clearing a value can un-satisfy a recommendation
   condition for OTHER attrs the same way changing it to a different
   value would).
5. `auto_fill`'s single-select branch (the `if vn in filled:` check,
   `engine.py`'s main per-attr loop) gains a new early check mirroring
   the existing multi-select one: `if filled.get(vn) == "" and
   sources.get(vn) == "user": display_filled[vn] = "(none)"; continue`
   — so a deliberately-cleared attr is never re-guessed by the blind
   first-by-order fallback on the next pass, exactly as `filled_multi`'s
   empty-but-user-sourced state already isn't.
6. If a LATER cascade genuinely re-derives this attr (a different change
   makes a recommendation/constraint rule fire for it again), the normal
   rule-governed fill path overrides the `"user"`-cleared state the same
   way a rule fill already overrides any other stale value today — D4
   only protects against the BLIND fallback re-guessing it, not against
   a real rule re-asserting a value once its condition becomes true
   again.

### 4.5 Q&A and value-change paths — no new code needed

STEP 7 (`_handle_cpq_qa`/`detect_attr_query`) and STEP 6
(`_handle_cascade`/`_handle_cascade_multi`) are already generic over
`filled`/`display_filled` state — nothing in either path assumes
"pre-confirmation." Reachable from `"post_approval"` via the same §4.1
widening, zero new logic.

**Dependent re-evaluation is guaranteed, not incidental.** Changing any
attribute's value — pre- or post-approval — already goes through
`_handle_cascade`'s existing mechanism, unchanged: `find_cascade_
dependents()` identifies every attr the changed one governs (via
hiding/recommendation/constraint rules), strips their current values from
`session.filled`, then re-runs the full `evaluate_rules_loop` + `auto_fill`
pass so every dependent is recomputed from the new state, not left stale.
Example: changing Hardware Version post-confirmation re-triggers the same
"Product depends on it and needs a fresh value — recalculating now"
cascade note this already produces pre-confirmation
(`docs/CPQ_SESSION_2026-07-22_ISSUES_AND_FIXES.md` item 3), and the
re-shown JSON reflects every recalculated dependent, not just the one
attr the client named. This is the existing STEP 6 contract — §4.1's
routing widening is what makes it reachable after confirmation, nothing
about the cascade mechanism itself needs to change.

### 4.6 Frontend — no changes required

`apps/web`'s JSON/Beautify buttons already re-render from whatever
`session_data`/`jsonResponse` the latest turn returns — confirming once
already re-shows updated JSON after every STEP-6 change today (pre-
confirmation). Nothing in the button/panel logic assumes a terminal
state, so post-confirmation edits surface identically with zero frontend
work.

## 5. What NOT to build (scope control)

- No "amend"/"reopen" intent — D1 makes this unnecessary.
- No ad-hoc custom-field addition — D2 restricts to real catalog attrs.
- No required-attribute removal — D3.
- No nullifying a required attribute, or one currently held by a
  still-active rule — D4.
- No multi-select "nullify" — declining/clearing a multi-select already
  works today via the existing empty-`filled_multi`-plus-`"user"`-source
  convention; D4 only adds the missing single-select counterpart.
- No new persisted "quote version history" — out of scope; each
  `/ask` turn's returned JSON is the current state, same contract as
  today. If real amendment audit trail is ever needed, that's a
  separate, later plan (would build on `session.cascade_log`, which
  already records every value change with old/new/turn).

## 6. Testing plan

New test files: `tests/test_cpq_post_approval_activation.py` (unit,
engine-level) and `tests/test_cpq_post_approval_flow.py` (API-level turn
sequences). Existing files referenced below stay unmodified except where
noted.

### 6.1 Unit — `detect_attr_activation` (engine-level)

| ID | Scenario | Setup | Assert |
|---|---|---|---|
| U1 | Matches a declined multi-select | Optional multi-select attr with `display_filled[vn] == "(none)"`, `filled_source == "user"` | Returns the attr; case = "declined" |
| U2 | Matches a flow-exclusion-dropped optional attr | Attr in `payload_flow_exclusions()`'s drop set, `required == False` | Returns the attr; case = "flow_excluded" |
| U3 | Matches a hiding-rule-excluded attr whose condition no longer holds | Hiding rule targets attr, condition was true at fill time, now false against current `session.filled` | Returns the attr; case = "hiding_rule", re-verified live (not cached) |
| U4 | Rejects a required attr in ANY pool | Same as U2/U3 but `required == True` | Returns `None` — required attrs are never candidates, regardless of source pool |
| U5 | Rejects an attr whose hiding condition is STILL true | Same as U3 but condition still holds | Returns `None` — proves the rule-bypass guard (§3, §7) actually holds, not just documented |
| U6 | Rejects a `attr.hidden == True` (BM-native) attr | Attr with source `hidden=1`, unrelated to any rule | Returns `None` — proves the `attr.hidden` vs. hiding-rule-hidden distinction (§4.2) is enforced in code, not just intent |
| U7 | Rejects an already-filled attr | Attr already has a real value in `session.filled` | Returns `None` — nothing to "add," it's already present |
| U8 | Case-insensitive / fuzzy label match | "add the extended warranty" vs. catalog label "Extended Warranty Plan" | Matches via the shared `_label_mentioned` matcher, same tolerance as every other detector |

### 6.1b Unit — `detect_attr_clear` (D4, engine-level)

| ID | Scenario | Setup | Assert |
|---|---|---|---|
| U9 | Matches a filled, optional, non-rule-forced single-select attr | `required==False`, `filled_source[vn] in ("user","default","optional","cascade")` | Returns the attr |
| U10 | Rejects a required attr | Same as U9 but `required==True` | Returns `None` |
| U11 | Rejects an attr currently forced by a still-active rule | `filled_source[vn]=="rule"`, governing rule's condition still true against `session.filled` | Returns `None` — the live rule re-check (D4 point 2) |
| U12 | Matches an attr that WAS rule-forced but the rule's condition no longer holds | `filled_source[vn]=="rule"`, condition now false | Returns the attr — same live-check discipline as U3/D2 case 3 |
| U13 | Rejects an attr with no value to clear | `vn` not in `filled` at all | Returns `None` — nothing to clear |
| U14 | Rejects a multi-select attr | Multi-select attrs are out of scope for D4 (§5) — falls through to existing removal detection instead | Returns `None` from `detect_attr_clear` specifically |

### 6.2 API — full turn sequences (`ask_api.py`, `_run_cpq_turn`)

| ID | Scenario | Turn sequence | Assert |
|---|---|---|---|
| A1 | Q&A about a specific value, post-confirmation | configure → confirm → "what's Hardware Version set to?" | Answered from `attr.options`/`filled`, no LLM synth needed (same fast path as pre-confirmation); `session.status` stays `post_approval` |
| A2 | Q&A about available options, post-confirmation | configure → confirm → "what are the options for Hardware Version?" | Numbered option list returned, identical shape to pre-confirmation `detect_attr_query` |
| A3 | Change a value WITH dependents | configure → confirm → change Hardware Version (has real rule-governed dependents, e.g. Product) | Every dependent invalidated + re-filled (not left stale); cascade note names them; new JSON reflects all changes, not just the one named |
| A4 | Change a value with NO dependents | configure → confirm → change an independent attr | Only that attr changes in the JSON; no unrelated cascade note appears |
| A5 | Remove an optional/multi-select attr | configure with a filled optional multi-select → confirm → "remove X" | Attr cleared, orphaned per-option quantity attrs cleared too (reuses existing `_handle_multi_select_removal`), JSON no longer contains it |
| A6 | Attempt to remove a REQUIRED attr | configure → confirm → "remove Hardware Version" (required) | Rejected — either silently not matched by any removal detector, or answered with an explicit "that's a required field, but I can change it to a different value" nudge (implementation choice; test locks in whichever is chosen) |
| A7 | Add back a declined optional multi-select | configure, decline an optional grid → confirm → "add back X" | Attr re-enters `pending` (asked like a normal question) or is filled directly if the message also supplies a value; never silently guessed |
| A8 | Add back a flow-exclusion-dropped attr | configure on a flow where an optional mirror attr is excluded → confirm → "add X" | Attr becomes askable; STEP 3 re-run confirms it doesn't reappear if the flow logic would exclude it again |
| A9 | Add back a hiding-rule-excluded attr, condition no longer true | configure, trigger the hiding condition, confirm → then CHANGE the condition-driving attr → "add X" | Attr becomes askable only now that the rule's live condition is false |
| A10 | Attempt to add an attr whose hiding condition is STILL true | Same as A9 but the condition-driving attr is never changed | Rejected — proves U5's unit guarantee holds at the full-turn level too, not just in isolation |
| A11 | Attempt to add a REQUIRED attr via activation wording | configure → confirm → "add Hardware Version" (already required, already filled) | Rejected/not matched — falls through to the normal change-request path instead (since it's phrased like activation but the target isn't a valid activation candidate) |
| A12 | Confirm again after edits (idempotency) | configure → confirm → change a value → "confirm" again | Re-shows the CURRENT (post-edit) JSON, not the original — proves confirm-after-edit isn't a stale cache |
| A13 | Legacy `"approved"` session (pre-migration compat) | Hand-construct `session_data` with `status: "approved"` (simulating a session confirmed before this ships) directly, skip the normal confirm turn | First action normalizes it to `"post_approval"`; all of A1-A12's behavior still works from this starting state |
| A14 | Ambiguous "add" vs "change" phrasing | configure → confirm → "add battery" where Battery Type is already filled with a real value | Resolved as a CHANGE (already-filled attrs are never activation candidates per U7), not a duplicate/conflicting add |
| A15 | Status transition sequence | Full flow from a fresh session to multiple post-confirmation edits | `session.status` transitions exactly `configuring → awaiting_approval → post_approval` and stays `post_approval` through every subsequent edit — never reverts to `configuring` |
| A16 | Clear an optional, non-rule-forced value | configure with an optional single-select filled by hint/default → confirm → "clear X" | `filled[vn]=="" `, `display_filled[vn]=="(none)"`, JSON no longer carries a value for it; a later turn's `auto_fill` pass does NOT re-guess it |
| A17 | Attempt to clear a REQUIRED attr | configure → confirm → "clear Hardware Version" | Rejected — required attrs are never clearable (D4 point 1) |
| A18 | Attempt to clear a value currently forced by an active rule | configure so a recommendation rule fills X and its condition is still true → confirm → "clear X" | Rejected — explains the value is currently rule-driven, matching D4 point 2 |
| A19 | Clear becomes possible after the forcing rule's condition changes | configure so a rule fills X → confirm → change the condition-driving attr so the rule no longer fires → "clear X" | Now succeeds — same live-check pattern as A9 |
| A20 | Cleared value doesn't resurface after an unrelated cascade | configure, clear an optional attr (A16) → confirm → change a DIFFERENT, unrelated attr | The cleared attr stays `"(none)"` after the unrelated cascade re-runs STEP 3 — proves the `"user"`-cleared marker survives a full rule-loop pass, not just the one turn it was set on |
| A21 | A genuine later rule re-asserts a cleared value | configure, clear X (A16) → confirm → change some OTHER attr whose recommendation rule targets X and now fires | X gets a real value again, from the rule — proves D4 point 6 (a real rule re-assertion overrides the cleared marker, same as it would override any other stale value) |

### 6.3 Regression

Full existing STEP 6/7/8 test suite (`test_cpq_e2e.py`,
`test_cpq_product_switch.py`, `test_cpq_bulk_quantity_change.py`,
`test_cpq_llm_intent_fallback.py`, `test_cpq_multi_select_removal.py`,
`test_cpq_label_collision.py`, and the rest of `tests/test_cpq_*.py`)
re-run unchanged against the widened `if` condition (§4.1) — proves
`"awaiting_approval"` behavior is provably untouched by this change, not
just "probably fine."

### 6.4 Live verification (real container, real catalog)

Replay a real quote end-to-end — e.g. APX Next Enhanced, workspace 14:
1. Configure and confirm.
2. Ask "what's the Hardware Version set to?" — confirm fast-path answer,
   no LLM round-trip needed.
3. Change Hardware Version to a value with real dependents — confirm the
   cascade note names every recalculated dependent and the JSON reflects
   all of them.
4. Remove a declined optional accessory — confirm it's gone from the
   JSON.
5. Add it back — confirm it's askable again, answer it, confirm it's
   back in the JSON with the new value.
6. Attempt to remove Hardware Version (required) — confirm it's refused
   or redirected to "change" instead.
7. Say "confirm" again — confirm the JSON shown matches every edit made
   in steps 2-6, not the original quote from step 1.

## 7. Risk

- **Blast radius:** low — the only structural change is widening one
  `if` condition (§4.1) and adding a new status value; STEP 6/7/8's own
  logic is reused unchanged, not rewritten.
- **Real risk, now a hard invariant (§3):** a hiding-rule-excluded attr
  becoming activatable (D2 case 3) must re-verify the hiding condition
  against CURRENT state, not stale state — a rule that hides attr X when
  Y=1 must not let X be "added" while Y is still 1 (that would silently
  violate the rule the exact same way a bypass would). `detect_attr_
  activation` must call `apply_hiding_rules` fresh, never trust a cached
  exclusion set. Enforced structurally by the `required == False` filter
  too — required attrs are never candidates in the first place, so this
  risk can only ever affect an optional field, never a payload-mandatory
  one.
- **Intent ambiguity:** "add battery" could mean "reactivate the Battery
  Type attribute" or be misread as a value for something else. §4.2's
  detector priority ordering handles the common cases; genuinely
  ambiguous phrasing falls to the same LLM intent-fallback path change/
  remove detection already uses (`8bc505a`) — which depends on the
  reason-tier LLM being correctly configured (this session already found
  that tier silently 404-ing once; see
  `docs/CPQ_CONVERSATIONAL_FLOW_FIXES_2026-07-23.md` context). A
  misconfigured reason model degrades add/remove detection quietly, not
  loudly — worth an explicit health-check, not just a try/except fallback.
- **Amplifies an existing risk, doesn't create one:** `api_share`
  (`/share-config`) is already available once `session.status !=
  "configuring"` — a rep could already share a snapshot pre-confirmation
  today and keep editing afterward, making the shared copy stale. This
  plan extends how long that "shared but still editable" window stays
  open; it doesn't introduce the drift risk itself. No real downstream
  order-submission integration exists today (confirmed — `build_payload`
  only returns JSON, nothing POSTs it anywhere automatically), so there
  is no live external system to go stale yet. If automatic downstream
  submission is ever added later, D1 ("stay live, no lock") should be
  revisited at that time.
- **New state combination, needs an integration sweep:** `filled[vn] ==
  ""` tagged `filled_source[vn] == "user"` for a SINGLE-select attr has
  never existed before this plan — every other place in the engine that
  reads `filled`/`display_filled` (`build_payload`, `beautify_rows`,
  `_filled_summary_triples`, `find_cascade_dependents`, etc.) needs
  auditing to confirm it treats this the same way it already treats
  multi-select's empty-plus-`"user"` `"(none)"` convention, not as "not
  yet answered." **Verified during live testing (§8): both already work
  correctly with zero code changes** — `build_payload`'s existing
  `if not v: continue` check already omits an empty-string value from
  the payload, and `_filled_summary_triples`'s existing
  `label.strip() != "(none)"` filter already excludes it from every
  summary/beautify view, generically, regardless of whether the
  "(none)" came from multi-select or (now) single-select.

---

## 8. Bugs found during live verification (fixed)

Live-verified against a real APX Next Enhanced quote (workspace 14,
rebuilt `aryx-api-1` container) — full D1/D4 turn sequence: configure →
confirm → Q&A → change-with-dependents → confirm → clear → add-back →
confirm. D1 (status transitions) and D4 (nullify) worked correctly on
first test; the sequence surfaced 2 real bugs, both in this plan's own
new code, neither in anything pre-existing.

### 8.1 Cascade-note wording didn't match the actual outcome

**Problem:** `_handle_attr_activation`'s cascade note always said "Added
**X** to your quote — what value would you like?", even when the
activated attribute resolved immediately via its own default value
(nothing left pending, `session.status` correctly stayed
`post_approval`) — the wording implied a follow-up question that never
actually came.

**Root cause:** The note was built with a fixed string BEFORE running
the rule-evaluation pass that determines whether the attribute actually
ends up pending or resolved.

**Fix:** Moved the note's construction to AFTER the pending-vs-resolved
decision (§4.3's override block) — it now states the real value
(`"Added **X** → **Y**."`) when one was determined, and only asks "what
value would you like?" when the attribute genuinely ends up in
`pending`.

### 8.2 Label-matching false positive on a shared generic word

**Problem:** "clear surveillance package type" (meant for the real
attribute "Surveillance Package Type") instead cleared an unrelated
attribute, "Customer Type" — confirmed reproducible, not a fluke.
Re-running "add surveillance package type" hit the identical wrong match.

**Root cause:** `_label_mentioned`'s word-set fallback tier (the
matcher every change-request/removal detector in this codebase already
shares) can, for a short 2-word label, degrade to requiring only its
LAST word to appear anywhere in the message — dropping "Customer" from
"Customer Type" leaves just "type", which trivially appears in almost
any message mentioning any other `*Type`-suffixed attribute. This tier
is explicitly documented as safe only as a coarse pre-filter, because
`detect_change_request` always requires a SEPARATE value-match
(`apply_answer`/numeric extraction) before actually resolving anything —
a loose label match alone never directly causes a wrong resolution
there. `detect_attr_activation`/`detect_attr_clear` have no such
secondary check: the label match IS the final decision, so they inherit
none of that backstop.

**Fix:** New `_label_mentioned_strict()` helper (`engine.py`) — same
exact-phrase and leading-word-drop tolerance for 3+-word labels, but
NEVER degrades a match below 2 remaining words (a 2-word label requires
the full phrase verbatim, no dropping at all). Used by
`detect_attr_activation`/`detect_attr_clear` in place of the shared
`_label_mentioned`. 2 new regression tests
(`test_clear_does_not_false_positive_on_a_shared_generic_word`,
`test_activation_does_not_false_positive_on_a_shared_generic_word`)
reproduce the exact real-catalog collision (`"Surveillance Package
Type"` vs. `"Customer Type"`) directly.

**First occurrence of this same class of bug, same fix — worth its own
record:** before landing on "Surveillance Package Type"/"Customer
Type," the very first phrasing tried was **"clear the surveillance
package"** (dropping the label's trailing word "Type"). That matched a
DIFFERENT unrelated attribute, **"ATAK Enabled Package"** — the
word-set fallback tier reduced "ATAK Enabled Package" down to its last
word, "package," which trivially appears in "clear the surveillance
package" too. `_label_mentioned_strict` fixes this exact collision the
same way (the word-set tier is gone entirely), confirmed by hand-tracing
both phrases through the new matcher — no separate code change needed
beyond §8.2's fix.

**Known limitation this fix introduces — a real, undocumented
tradeoff, not free:** neither the original phrasing ("clear the
surveillance package") nor any other TRAILING-word-dropped phrasing
matches the real target ("Surveillance Package Type") even with the fix
— it now correctly matches NOTHING (falls through to "I didn't catch
that") rather than silently matching the WRONG thing, but it still
doesn't match the RIGHT thing either. `_label_mentioned_strict`
inherits the same "leading-drop only" limitation as `_label_mentioned`'s
own tiers 1-2 — this is the identical trailing-word/reordered-phrase gap
already flagged as open in
`docs/CPQ_SESSION_2_MASTER_ISSUES_AND_FIXES.md` item 5 ("only handles a
dropped PREFIX, not a REORDERED phrase... still open," deliberately
deferred pending a decision on false-positive risk). `detect_change_
request` tolerates this gap today by keeping the looser word-set tier
available, backstopped by its own separate value-match check — D2/D4
gave that tier up entirely for safety (§8.2), trading recall for
precision, since they have no equivalent backstop to lean on. Not fixed
here; flagged as a shared, pre-existing, cross-cutting gap that a future
pass at item 5 (word-SET matching, order-independent, with a decision on
false-positive risk) would need to resolve for ALL detectors at once,
not just these two.

### 8.4 Scope clarification (not a bug): re-filling a D4-cleared attr

Live testing also confirmed a D4-cleared attribute is correctly
re-fillable via the existing, UNMODIFIED change-request path ("set
Surveillance Package Type to Beige" works exactly as it always has) —
`detect_attr_activation` deliberately does NOT treat a cleared attr
(`filled[vn] == ""`) as an activation candidate, since D2's activation
is specifically for attributes structurally excluded from the quote
(flow/hiding-rule exclusion, declined multi-select), not for one the
user just cleared themselves. "Add X" with no destination value for a
cleared attr correctly falls through to a generic nudge rather than
silently guessing — re-filling it needs an actual value, exactly like
answering any other pending question would.
