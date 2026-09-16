# CPQ Mid-Configuration Change-Request Plan

Status: scoped, not implemented — awaiting approval to build.

## Problem

Once Amendment 22 (`docs/CPQ_UNIFIED_INTENT_CLASSIFIER_PLAN.md`) correctly
restored `agencyDomainName_ID_swSoln` (and similar free-text fields) to the
`pending` list, a live repro surfaced a change-request no longer applying:

```
turn 1 "yes"                                     -> fedramp=FEDRAMP, pending[0]=agencyDomainName_ID_swSoln
turn 2 "change Is FedRamp or CCCS Required to None" -> fedramp=FEDRAMP  (unchanged!)
...
final fedramp: FEDRAMP   (never became NONE)
```

**Root cause, confirmed by direct code read**: change-request handling
(`detect_change_request`, `detect_change_request_collision`,
`detect_change_requests_multi`, `_handle_cascade`, and everything else STEP
6/7/8 covers) lives entirely behind one gate in `_run_cpq_turn`
(`src/aryx/api/ask_api.py:3300`):

```python
if session.status in ("awaiting_approval", "post_approval"):
```

There is no code path for "change an already-filled attr while the
configuration is still collecting other pending answers." A message like
"change Is FedRamp or CCCS Required to None" sent mid-configuration falls
through to ordinary pending-answer processing (STEP 5,
`ask_api.py:3832`), doesn't match the currently-pending attr's expected
answer shape, and is silently dropped.

**This is not a new regression** — before today, `agencyDomainName_ID_swSoln`
was never pending (Amendment 20's revert), so the CC Aware flow completed in
2 turns flat and every "change X" message a real user sent always arrived
after `awaiting_approval` was already set, so STEP 6 always fired. Amendment
22 (correctly) makes the flow take longer to complete, which is the first
thing in this session to expose a mid-configuration change-request at all.

## Why this is worth fixing generically, not just for FedRamp

Any attr that gets auto-filled (by a recommendation rule, a default value,
or an auto-fill fallback) before the user reaches the end of a longer flow
is exposed to this same gap — the FedRamp case is just the one a live
transcript happened to hit. A real user has no way to know internally
whether the flow they're in will complete in 2 turns or 10; from their side,
"change X" should work identically regardless of how many other fields are
still outstanding.

## Scoped fix

**Insertion point**: a new block in `_run_cpq_turn`, immediately before
STEP 5 ("Lock user's answer from previous turn", `ask_api.py:3832`) and
after the existing Q&A / label-collision / pending-question-collision
checks above it. This ordering matters:
- Must run **after** STEP 7's Q&A gate and the new Amendment 21 free-text
  constraint check, so "what values are available for X" is never misread
  as a change request.
- Must run **before** STEP 5, so the raw message never gets treated as a
  (garbage) answer to whatever happens to be pending right now.

**Detection**: reuse the exact same detectors already used in the
awaiting_approval path unchanged — `detect_change_request_collision`,
`detect_change_requests_multi`, `detect_change_request` — no new NLP
surface. They already require the named attr to be present in
`session.filled` (i.e. genuinely already answered), so a message about the
CURRENTLY PENDING (not-yet-answered) attr can never be misdetected as a
change here; that keeps falling through to STEP 5 exactly as it does today.

**Applying the change**: call `_handle_cascade` (`ask_api.py:513`)
unmodified. It does not assume the configuration is complete — it already
sets `session.status = "configuring"` (not `awaiting_approval`) when the
recomputed `pending` list is non-empty after invalidating dependents (e.g.
`ask_api.py:601`, `746`), and `awaiting_approval` when it resolves back to
empty. That means it should already produce the right status either way;
this is presumed reusable as-is, to be confirmed once implemented.

**Reconciling pending**: after the cascade, the previously-outstanding
pending attr(s) (e.g. `agencyDomainName_ID_swSoln`, still unanswered) must
stay pending unless the change genuinely invalidated them as a dependent —
`_handle_cascade`'s own dependent-invalidation logic (`find_cascade_dependents`)
already decides that; no new merge logic should be needed as long as the
attr the user was mid-answering isn't itself a dependent of the change.

## Risks / open questions to verify once built

1. **Ordering conflicts** with Amendment 17 (`_llm_extract_multi_attr_hints`)
   and Amendment 16 Layer 2 (disambiguation composer) — both also run
   somewhere in this same turn-processing region; confirm none of them
   consume the message first in a way that prevents the new change-request
   check from ever seeing it.
2. **False positives**: a message that both names a filled attr's value AND
   plausibly answers the pending question (rare, but possible with a dense
   sentence) — `detect_change_request`'s existing verb-vocabulary
   requirement (`_CHANGE_VERB_RE`) should already guard against this, since
   it's the same detector the awaiting_approval path already trusts.
3. **Test coverage**: needs new test scenarios — a mid-config change that
   (a) succeeds and correctly updates `filled`/`filled_source`, (b) doesn't
   regress a normal pending-answer turn when no change verb is present, (c)
   doesn't regress any existing awaiting_approval-path cascade test.
4. **Live verification**: re-run the exact FedRamp repro from Amendment 22's
   verification (`fedramp_trace2.py`-style script) and confirm `filled`
   shows `NONE`/`source=user` immediately after the change turn, not just
   at final completion.

## Not in scope here

- The frequency-band Q&A leak (separate, untraced finding from the same
  live session — "three dummy frequency band attributes... set to false"
  leaking internal graph/data-modeling detail into a customer-facing
  answer). Tracked separately, not addressed by this plan.

## Related finding 1: "change hardware version" / "change X" with no value given gets no clarifying question

Found live in the same transcript that surfaced the frequency-band leak.
"I want to change hardware version" and "change product" (naming the attr,
no new value) both fell straight through to the generic "I didn't quite
catch that" nudge instead of asking "which value would you like?" —
confirmed the user's own ask (issue 1): the system should recognize the
change *intent* and prompt for the missing value, not just fail silently.

**Root cause, confirmed by direct code read**: the full
change-request-detection chain in `_run_cpq_turn`
(`src/aryx/api/ask_api.py:3600-3663`) is:

1. `detect_change_requests_multi` — regex, requires 2+ resolved values.
2. `detect_change_request` — regex, requires one resolved value.
3. `_llm_classify_change_intent` — LLM fallback, but its own contract
   (`{"intent": "change"/"remove", "variable_name", "value"}`) still
   requires a resolved `value` field to act on.
4. Nothing left → generic "I didn't quite catch that" summary nudge.

Every layer, regex AND LLM, assumes a resolvable new value is present in
the message. There is no branch anywhere for "recognized WHICH attr the
user wants to change, but not to what" — that case is indistinguishable
from total gibberish by the time it reaches the final nudge.

**Scoped fix**: add one more fallback tier after step 3 above, before the
generic nudge: if `_llm_classify_change_intent` (or a lighter-weight
regex/keyword check — `_CHANGE_VERB_RE` plus a name match against
`session.filled`, no value) recognizes a change-verb naming an
ALREADY-FILLED attr but produces no resolvable value, respond with that
attr's available options (reuse `detect_attr_query`'s existing
options-listing block verbatim, `ask_api.py:3706-3717` — same "Here are
the available values for X..." presentation already used for "what values
are available") and set `pending_variables` so the next answer is
captured as the new value via the existing pending-answer/STEP-5 path,
exactly as `_label_collision`-style flows already do. No new UI or answer
format — just correctly recognizing the intent and reusing what's already
there for a value-less change.

**Open question**: should this become part of the same mid-config
change-request work above, or ship independently? They touch the same
code region (`_run_cpq_turn`'s STEP 5/6/7 area) — bundling both into one
pass avoids two separate ordering-conflict reviews of that region.

## Related finding 2: options-query answers ignore already-selected constraints

Found in the same transcript: "what are the values available for
Product?" (with Hardware Version already set to APX NEXT 4G LTE+5G)
returned all 325 raw catalog product codes — Product's entire cross-family
list, completely unfiltered by the current selection.

**Root cause, confirmed by direct code read**: the Q&A options-listing
fast path (`ask_api.py:3706-3708`) calls
`_cpq_engine.next_question_prompt(queried_attr)` with no
`constrained_item_values` argument, so it always defaults to `None` (no
filtering) and lists every `attr.options` entry regardless of active
constraint rules. Compare the normal pending-question flow, which computes
`constrained_opts = apply_constraint_rules(attrs, con_rules, filled, bml_eval)`
and passes `constrained_opts.get(attr.entity_id)` into this same
`next_question_prompt` call — the Q&A path simply never does this.

**Scoped fix**: at the Q&A options-query call site, compute
`constrained_opts` the same way the main flow already does (con_rules are
already loaded earlier in `_run_cpq_turn`) and pass
`constrained_opts.get(queried_attr.entity_id)` through. Small, mechanical
change — reuses `apply_constraint_rules`, no new logic. Risk is low: this
function is already called with this exact pattern elsewhere in the same
file, so it's a proven code path, not new machinery.

**Confirmed, not just an open question**: `productSelectionProduct_all`'s
governing constraint rule is plain Tier-1 (`if(hWVersion_astro=="NEXT
ENHANCED LTE PLUS 5G"){"APX NEXT ENHANCED|^|APX NEXT XE 4G LTE PLUS 5G"}
else{...8 other variants...}`) — no Tier-2/LLM needed. With Hardware
Version set to APX NEXT (4G LTE+5G) as in the live transcript, this should
narrow the 325-item catalog list down to exactly 2 real options. `bml_eval`
is already available in `_run_cpq_turn`'s scope at the Q&A call site (used
elsewhere in the same function), so no new evaluator wiring needed either
— this really is just a missing argument, not missing machinery.
