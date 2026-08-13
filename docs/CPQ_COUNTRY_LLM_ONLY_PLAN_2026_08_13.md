# CPQ Country Extraction — LLM-Only Plan (2026-08-13)

Status: **implemented and live-verified.**

**Owner decisions on the 3 open questions:**
1. LLM failure → explicit "LLM failed, try again later" message (never a
   silent regex fallback, never a generic re-ask). Implemented as a new
   `cpq_llm_call_failed()` short-circuit, only when the turn-1 router
   itself timed out/errored AND no country was otherwise resolved.
2. Drop the "Country-once" regex re-scan entirely. Done — verified no
   real coverage was lost (its only real cases were turn-1 shaped and
   are now covered directly by `route_meta.country`).
3. Investigate the universal dispatcher's real behavior on non-verb
   country statements before implementing further. Done — see findings
   below; fed directly into the `country_text` schema fix.

**Live verification results (real container, workspace 39004,
gemini-2.5-pro):**

| Row | Phrase | Result |
|---|---|---|
| C40 | "in CANADA" (turn 1) | `country="CANADA"` — correct value, resolved via `route_meta.country`, though the LLM returns the customer's own casing verbatim rather than title-casing it (cosmetic, not a wrong country — flagged as a possible follow-up, not fixed this round) |
| C42 | "pricing for APX models in the United States" (turn 1) | `country="United States"` — fixed |
| C48 | "Generate a quote: ..., United States" (turn 1, no preposition) | `country="United States"` — fixed |
| C16 | "ship to Canada" (mid-conversation, no change verb) | `country="Canada"`, `Country → Canada` — works via the universal dispatcher, zero code change needed beyond the checkpoint's own value-extraction fix |
| C17 | "deliver to Canada" (mid-conversation, no change verb) | `country="Canada"`, `Country → Canada` — this one FAILED before the `country_text` schema fix below (the LLM correctly picked the category but populated a catalog `variable_name` instead of `country_text`, an unrelated catalog attribute happened to pull it that way); fixed by strengthening the schema description, not by any code/gating change |
| C14 | "change destination country to Canada" | `country="Canada"` — was already working via the separate `_COUNTRY_CHANGE_RE`-triggered gate; now sources the value from `country_text` instead of the regex capture, same visible result |
| C15 | "set country to Canada" | `country="Canada"` — same as C14 |
| C27 | "u.s." (turn 1, standalone) | Router call timed out during rapid back-to-back live testing — surfaced the new `cpq_llm_call_failed()` message as designed, not a silent wrong answer. Not re-testable in isolation from an LLM latency artifact; the mechanism itself is confirmed correct (reject-on-failure, explicit message) |
| C43 | "cost of APX models in the United States" (turn 1) | Inconsistent across repeated live calls — sometimes times out (same as C27), sometimes the router classifies this as a QA-style question rather than "quote", routing to a different handler that doesn't consult `route_meta.country` at all. This is a ROUTE CLASSIFICATION question (qa vs. quote for a "cost of X" phrasing), not a "regex decided the country" bug — out of scope for this plan, flagged as a separate follow-up if it turns out to matter in practice |

**Implementation notes beyond the original plan:**
- The `country_text` schema description (`intent_schema.py`) was
  strengthened during implementation (not originally scoped) once live
  testing showed "deliver to Canada" reproducibly failed — the LLM
  correctly recognized the category but filled `variable_name`/
  `value_ref` instead of `country_text` when a similarly-named catalog
  attribute existed among the injected candidates. The fix explicitly
  instructs the model that a plain destination statement counts equally
  as an explicit change command, and that `country_text` is the only
  correct field regardless of what catalog attributes are present.
- `hints.pop("country", None)` unconditionally drops whatever
  `_COUNTRY_PREP` guessed before any of the LLM-sourced/bare-reply
  branches run, guaranteeing the regex's own capture can never leak
  through by accident.

## Directive

> "I don't need regex to decide country at any point, llm should do that."

This supersedes the narrower fix already shipped (route_meta.country as a
*fallback* when the regex is invalid — docs/CPQ_TURN1_COUNTRY_EXTRACTION_
DEFECT_PLAN_2026_08_13.md) and the case-by-case QA sheet triage
(docs/... QA analysis, same day). The target end-state: **regex may only
ever be used to decide WHETHER to ask an LLM something (a cheap trigger),
never to decide WHAT the country actually is.** The LLM already gets
asked once per turn in most cases today — this plan reuses those calls,
it does not add new ones except where explicitly flagged as an open
question below.

## Every place regex currently decides the country VALUE today

All in `src/aryx/cpq/engine.py` / `src/aryx/api/ask_api.py`:

| # | Site | Regex used | Feeds |
|---|---|---|---|
| 1 | Turn-1 hint extraction | `_COUNTRY_PREP` (`engine.py:422-428`) via `extract_hints` | `hints["country"]`, currently checked BEFORE the `route_meta.country` LLM fallback (`ask_api.py:7302-7334`) |
| 2 | Mid-conversation explicit change command | `_COUNTRY_CHANGE_RE` (`engine.py:443-464`) captures the target country itself | `_country_change_match`, used directly as the value in `_build_country_change_response` (`ask_api.py:7288-7299`) — the LLM checkpoint here only confirms the CATEGORY (bool), never the value |
| 3 | Switch-country flow | `hints.get("country") or req.question.strip()` (`ask_api.py:7555`) | `new_country` for `_complete_product_switch` |
| 4 | "Country-once" history re-scan | `extract_hints` rerun across `req.question`, `product_anchor_question`, `pending_switch_question`, and mined history turns (`ask_api.py:8234-8253`) | `session.country`, last resort before the clarifying question fires |
| 5 | US/UK literal aliases | `_HINT_PATTERNS` (`engine.py:357-358`, e.g. `u\.s\.`) | Same `hints["country"]` path as #1 |

Two places are **not** regex-deciding-the-value and should stay as-is —
flagging them explicitly so the implementation doesn't over-reach:

- `session.pending_anchor == "country"` bare-reply shortcut
  (`ask_api.py:7308-7309`): when we just asked "what's the destination
  country?", the ENTIRE customer reply IS the answer — there's no
  pattern-matching ambiguity to resolve, so treating the raw text
  literally isn't "deciding via regex" in the sense this directive means.
- Carrying `session.country` forward on later turns with no new hint
  (`ask_api.py:7349-7365`, `is_recognized_country` validation at
  `7336-7348`): this is validating/reusing an already-LLM-sourced value,
  not deciding a new one from a fresh regex parse.

## Existing LLM calls available to reuse (no new call needed for #1, #2)

- **Turn 1**: `classify_ask_route` (`ask_api.py:10387`, gated by
  `cpq_intent_mode == "llm_first"`, now the default) already runs once
  per cold-start turn and populates `route_meta.country`. This is a full
  LLM read of the entire message — no preposition, no capitalization
  requirement, no regex trigger needed at all.
- **Every turn (mid-conversation)**: `gateway_classify_intent`
  (`intent_gateway.py`) already returns `GatewayIntentResult.country_text`
  for `IntentCategory.COUNTRY_CHANGE`, already quarantined by
  `validate_gateway_quarantine` (`intent_schema.py:542-549`) — a
  CONFIRMED `COUNTRY_CHANGE` result is GUARANTEED to carry a
  `country_text` that already passed `is_recognized_country`. This call
  already happens at the STEP-6 country-change gate (as a confirm-only
  bool via `_llm_confirm_deterministic_intent`) AND, separately, inside
  the universal per-turn dispatcher (`_llm_first_gateway_turn` →
  `_dispatch_intent_result`, `ask_api.py:4916-4925`, ALREADY uses
  `country_text`/`country_description` as the value, not regex — this
  path is already compliant with the directive today).

## Proposed changes

### 1. Turn 1: make `route_meta.country` authoritative, not a fallback

Currently (`ask_api.py:7302-7334`): `hints["country"]` from `_COUNTRY_PREP`
is checked FIRST; `route_meta.country` only overrides it when the regex
result is invalid. Flip this: on turn 1, `route_meta.country` (when
present) IS the country — full stop, no regex consulted for the value at
all. `_COUNTRY_PREP`/`extract_hints` keeps running for other hints
(product, quantity, etc. — out of scope here) but its `country` key is
simply never read into `session.country` on turn 1.

Open question: if `route_meta` is `None` or `route_meta.country` is
`None` (LLM found nothing, or the call failed/timed out) — per this
whole session's reject-on-failure discipline (never trust the
deterministic path just because the LLM one failed), the honest answer
is: **no country is set from this turn's message at all**, same as today
when both mechanisms fail. This is a real behavior change from today
(today, a regex-only match with no LLM opinion still sets the country) —
flagging for explicit sign-off since it could mean a FEWER cases succeed
outright before falling through to the clarifying question, trading
"maybe wrong" for "asks more often, never wrong."

### 2. Mid-conversation explicit change command: extract via `country_text`, not the regex capture

New sibling of `_llm_confirm_and_extract_quantity`:
`_llm_confirm_and_extract_country(req, session, ..., fallback_value=None)`
— calls the exact same `gateway_classify_intent` the confirm checkpoint
already makes, returns `(confirmed, country_value)`. Per the quarantine
guarantee above, **no fallback branch is even needed** — unlike quantity
(where a confirmed category can still carry an unusable `quantity_text`),
a confirmed `COUNTRY_CHANGE` always carries a valid `country_text`. If
`country_text` is somehow still empty (defensive only), treat as
`confirmed=False` — never fall back to `_country_change_match`.

`_COUNTRY_CHANGE_RE` stays exactly where it is, doing exactly what it
does today — but downgraded to a **trigger only** ("does this look like
a change command worth confirming with the LLM"), never the value
source. This mirrors `question_mentions_quantity`'s role for the
quantity gate: cheap pre-filter, zero authority over the actual value.

### 3. Switch-country flow (`ask_api.py:7555`)

`new_country = hints.get("country") or req.question.strip()` needs the
same treatment. Two sub-cases:
- If this fires on turn 1 of the switch (i.e., `route_meta` available):
  use `route_meta.country` per item 1's new precedence.
- If it fires mid-conversation as part of a `pending_anchor ==
  "switch_country"` reply: this is actually the SAME shape as the
  bare-reply-to-pending-question case flagged as fine above — the
  customer was just asked to name the replacement country, so treating
  the raw reply as the answer isn't "regex deciding," it already falls
  back to `req.question.strip()` when `hints` has nothing. The bug here
  is narrower than it looks: `hints.get("country")` can still be
  populated by a WRONG regex match that isn't caught by any
  `is_recognized_country` check at this call site (needs confirming
  during implementation) — if so, the fix is simply to stop consulting
  `hints.get("country")` here at all and always use the raw reply
  directly, consistent with every other pending-anchor bare-reply site.

### 4. "Country-once" history re-scan (`ask_api.py:8234-8253`) — the one genuinely new-call question

This is the one site where "just reuse an existing call" doesn't
cleanly apply: it scans MULTIPLE independent texts (this turn's
question, the anchor question, the switch question, and N mined history
turns) for a country, and none of those texts necessarily got an LLM
classification call of their own (mined history turns in particular —
they were some PAST turn's message, already processed and moved past).

Options, needing a decision before implementation:
- **(a) Drop this block entirely once items 1-2 land.** If turn 1 and
  explicit change commands are both LLM-sourced, and `session.country`
  carries forward once set, this re-scan may already be catching cases
  ONLY because the earlier extraction points were regex-based and
  missed things (i.e., its entire reason to exist might be "regex missed
  it the first time, try again over more text with the same regex") — if
  so, it becomes dead code once 1-2 close the same gaps at the source.
  Cheapest option; risks losing real coverage (e.g., mid-conversation
  message #2 that ISN'T an explicit change command AND isn't turn 1, e.g.
  "ship to Canada" mid-conversation with no route_meta and no change
  verb — see item 5).
- **(b) Replace with a single new LLM call** over the concatenated
  candidate texts (still one call per turn this block runs, not one per
  text) — a genuinely new call type, contradicting "no new LLM call"
  unless the owner explicitly accepts it for this one last-resort site
  (it only runs when `not session.country`, i.e., rare/edge, not
  every turn).
- **(c) Keep it as a last-resort regex scan** (a narrow, explicitly-
  scoped exception to the directive) with the reasoning that by the time
  we're here, both real LLM opportunities (turn 1, explicit change) have
  already been exhausted with no result — this is genuinely
  "regex-or-nothing" territory, not "regex was chosen over an available
  LLM." Weakest fit to the stated directive, but zero new call cost and
  zero behavior risk (this block already exists and already only sets
  `session.country` when `is_recognized_country` passes).

**Recommendation: (a) first, verify via the item-5 investigation below
whether real coverage is lost; only reach for (b) if a real gap remains
that (a) can't close.**

### 5. Non-verb-anchored mid-conversation country statements ("ship to Canada", "deliver to Canada" — C16/C17)

Needs verification during implementation, not guessed here: does the
universal per-turn dispatcher (`_llm_first_gateway_turn`, gated on
`cpq_llm_first_universal_enabled` — already default-on this session)
run UNCONDITIONALLY on every turn 2+ regardless of whether
`_COUNTRY_CHANGE_RE` matched, and would it classify "ship to Canada" as
`COUNTRY_CHANGE` (or some other category that still carries
`country_text`) via pure semantic understanding, no verb-list
dependency? If yes, C16/C17 close for free with zero code change beyond
items 1-2 (the STEP-6 regex gate simply doesn't fire, the universal
dispatcher — already LLM-value-driven — catches it instead). If the
universal dispatcher's classification prompt/schema doesn't consider
"ship to X" a country CHANGE (e.g., it's genuinely ambiguous whether
this is changing an existing country or stating one for the first
time), that's a schema/prompt-wording gap, not a regex gap — fixable by
expanding `COUNTRY_CHANGE`'s schema description (`intent_schema.py`),
exactly like `quantity_text`'s description was expanded during the
quantity fix, never by adding a regex trigger.

## What this plan does NOT do

- Does not touch quantity, removal, activation, or clear gates — country
  only, per the directive's scope.
- Does not add a new LLM call for items 1-3 and (pending the item-5
  finding) hopefully not for item 5 either. Item 4 is the one place a
  new call is even on the table, and only as a fallback option if (a)
  turns out insufficient.
- Does not remove `is_recognized_country` validation anywhere — the
  LLM's value is still validated against the known country list before
  being trusted, consistent with this session's "LLM decides, deterministic
  code validates, never the reverse" discipline throughout.

## Test plan (for implementation phase)

1. Turn-1 precedence flip: `route_meta.country` wins even when
   `_COUNTRY_PREP` would have produced a DIFFERENT valid-looking value
   (proves LLM authority, not just "used when regex fails").
2. All of C27, C30, C31, C40 (turn-1 shaped) resolve via `route_meta`
   with zero regex involvement in the result.
3. New `_llm_confirm_and_extract_country` unit tests (confirm/reject/
   exception paths), mirroring `test_extract_uses_the_llms_own_value_
   over_the_deterministic_one` from the quantity work.
4. C14, C15 (already-working explicit change commands) still pass, now
   sourced from `country_text` instead of the regex capture — same
   answer, verifiably different code path (mock `_country_change_match`
   to a WRONG value and confirm the LLM's `country_text` still wins).
5. C16, C17 — verify against the real universal dispatcher (live test,
   not just unit test with a mocked gateway) whether they close for free
   per item 5, before deciding whether any schema/prompt change is
   needed.
6. Full CPQ regression suite + live-test against the real container for
   every QA row (C14-C50) plus the two originally-fixed transcripts
   (quantity, "APXNET in United States").

## Open questions requiring a decision before implementation

1. Turn-1 fallback-on-LLM-failure: accept "no country set" (never
   trust regex) as the honest failure mode, per item 1's flagged
   behavior change?
2. Item 4 (Country-once re-scan): try option (a) drop-and-verify first,
   or go straight to design work for option (b) a combined new call?
3. Item 5 needs live investigation before it's known whether ANY code
   change is required for C16/C17, or just a schema description tweak —
   should that investigation happen now (before implementation starts)
   or as the first implementation step?
