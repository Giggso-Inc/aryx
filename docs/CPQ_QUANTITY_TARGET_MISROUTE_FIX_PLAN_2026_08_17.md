# CPQ Quantity Target Misroute — Fix Plan

**Date:** 2026-08-17
**Branch:** `fix/cpq-quantity-target-misroute` (from `dev-rv-msi` @ `ab1f477`, post PR #205)
**Status:** Implemented (LLM-reinforced design, see "Design pivot" below), unit-tested
(49/49 passing in `test_cpq_session_product_quantity.py`); live redeploy/replay pending
**Severity:** High
**PR:** #208

## Problem

Reported via a live customer transcript (APX NEXT quote flow). After a Product change
triggers a large (~140-attribute) cascade recalculation, the customer sends an ordinary,
unambiguous top-level request:

> "can you change that quantity to 5"

— referring to the overall order quantity, which was just shown in the previous turn's own
summary as "Quantity → 1". Instead of updating the overall quantity, the system responds:

> "Which value would you like for Quantity (VX650 Item Type)? Quantity Please provide a value."

— misrouting to an obscure, per-catalog sub-attribute the customer was never shown or asked
about at any point in the conversation.

Note: the *value* (5) is never in question — it parses correctly every time. The entire bug
is in deciding *which field* the value should be written to.

## Root cause

Confirmed by direct code read, not inference.

1. `quantity_turn_precheck()` (`src/aryx/cpq/engine.py:1227`) correctly detects a
   quantity-change attempt with value=5 — this part works.
2. The caller (`src/aryx/api/ask_api.py:7579-7583`) builds `_qty_candidates` — the set of
   catalog quantity attributes allowed to compete with the overall product quantity — by
   checking only:
   ```python
   _qty_candidates = [
       a for a in _qty_pre["candidates"]
       if a.variable_name in session.filled
       or a.variable_name in session.filled_multi
   ]
   ```
   This checks *presence*, never *provenance*. An attribute that was purely auto-filled as a
   side effect of the preceding Product-switch cascade — never seen, never chosen by the
   customer — counts identically to one the customer genuinely set.
3. Confirmed via `grep` across `engine.py` (lines 6047-8733): every cascade/auto-fill path
   tags its writes with a non-customer source — `"rule"`, `"default"`,
   `"default_first_available"`, `"data_table"`, `"blind_pick_governed"`, `"cascade"` — never
   `"user"`. The codebase already has an established convention for exactly this distinction:
   `_WEAK_SOURCES = {"default", "rule", "auto"}` (`engine.py` ~6314), used elsewhere
   (`exclusive_sibling_family_exclusions`) to avoid trusting a non-customer-confirmed value.
4. Because the VX650 quantity attribute became a "candidate" purely through cascade
   provenance, `_llm_resolve_quantity_target()` (`ask_api.py:5905-5954`) was called to choose
   between "product" and that candidate. Its prompt gives the LLM no signal about what was
   recently shown or discussed — it guessed the never-mentioned catalog attribute over the
   quantity the customer had just been shown.

## Fix design (superseded — see "Design pivot")

A naive fix (require `filled_source == "user"` to even become a candidate) was considered
and rejected during planning: it would also exclude a candidate the customer explicitly
*names* in the same message (e.g. "change the VX650 item type quantity to 5"), silently
misrouting the opposite way if that attribute was only ever cascade-filled.

The first shipped version replaced the LLM auto-resolve step with a fully deterministic
three-branch resolution (explicit name match wins outright; a generic reference could only
be contested by a `filled_source == "user"` candidate; otherwise straight to product). A
follow-up code review found a Critical regression in that design (see "Design pivot" below),
and an explicit decision was made to revert to an LLM-based resolver rather than patch the
pattern-matching approach further.

## Design pivot (2026-08-17, post-review)

**Review finding (Critical):** the deterministic name-matcher's "a digit-bearing token is
trusted alone" rule had no lower bound on specificity — it matched on a coincidental digit
being the quantity VALUE itself, not a reference to the attribute. E.g. a candidate labeled
"Quantity for Tier 2 Bundle" (any provenance) plus the message "change the quantity to 2"
would false-match on the shared token "2", misrouting to the irrelevant bundle attribute —
reproducing this PR's own bug class via a new mechanism.

**Decision:** rather than tighten the pattern-matching rule further (e.g. requiring
alnum-mixed tokens), explicitly reverted to an LLM-based resolver — reinstating
`_llm_resolve_quantity_target()` — but reinforced this time with exactly the context the
original version was missing:

1. Each candidate line in the prompt now carries its `filled_source` provenance
   (`"user"` vs `"cascade"`/`"default"`/`"rule"`/...), with explicit instruction that a
   non-`"user"` source means the customer likely never saw or chose that field.
2. Explicit bias rule: a generic/bare reference should almost always resolve to `"product"`
   unless the message clearly, specifically names an item.
3. Explicit anti-digit-coincidence guard: a bare digit inside a candidate's own label is
   never itself a reference to that candidate, closing the Critical finding's exact failure
   mode without any pattern-matching code.
4. Added a log line (the review's High finding) when the LLM resolves to `"product"` despite
   a non-`"user"`-sourced candidate being present — observability for this fallback path.
5. Removed `question_names_quantity_attr()` and its dedicated tests entirely (dead code once
   the LLM path was reinstated) — replaced with a prompt-content test
   (`test_llm_prompt_carries_provenance_and_anti_digit_coincidence_guidance`) asserting the
   provenance and anti-digit guidance actually reach the model, since a unit test can't
   directly verify a live model's judgment.

**Trade-off, stated plainly:** this restores per-turn LLM latency/cost for any turn with a
real competing candidate, and the fix is now "very likely correct" rather than "provably
correct" the way a tightened deterministic rule would have been. Accepted deliberately in
favor of the established design principle from the PR #205 review round: reinforce the LLM
with proper context rather than routing judgment calls through pattern-matching.

## Verify before implementing

- Replay the reported transcript live end-to-end; confirm `quantityVX650ItemType_astro` (or
  equivalent) has `filled_source == "cascade"` (or another non-`user` tag) after the Product
  switch, confirming the hypothesis with live data, not just static code reading.
- Confirm the explicit-name-match branch resolves correctly for a message naming a
  cascade-only-filled item (the case the naive single-filter fix would have broken).
- Confirm the generic-reference + no-real-candidate case goes straight to product quantity
  with zero LLM calls.
- Confirm the generic-reference + genuine prior user-set item case still asks the clarifying
  question.
- Re-run the existing CPQ regression suite for no unrelated regressions.

## Implementation (current, post-pivot)

- `src/aryx/api/ask_api.py` — reinstated `_llm_resolve_quantity_target()` with the reinforced
  prompt described above; the gate's candidate list is back to a pure presence filter
  (`session.filled`/`filled_multi`), unchanged from before this fix — the fix lives entirely
  in what the LLM is told, not in how candidates are filtered. Added the High-finding log
  line for the "product despite non-user candidate" observability path.
- `src/aryx/cpq/engine.py` — `question_names_quantity_attr()` and its generic-label-word
  constant removed; docstrings/comments reverted to point at the LLM resolver again.
- `tests/test_cpq_session_product_quantity.py` — restored the original LLM-mocked gate tests
  (`test_named_catalog_attribute_falls_through_to_normal_pipeline`,
  `test_ambiguous_bare_quantity_with_competing_attribute_asks_disambiguation`,
  `test_disambiguation_resolving_to_product_answers_from_session`), restored
  `test_llm_resolve_quantity_target_rejects_invented_variable_name`, kept
  `test_explicit_named_attribute_wins_even_when_only_cascade_sourced` (now LLM-mocked), and
  added `test_llm_prompt_carries_provenance_and_anti_digit_coincidence_guidance` (the Medium
  finding, adapted for the LLM design — asserts the prompt itself carries the provenance and
  anti-digit-coincidence signal, since a mocked unit test can't verify live model judgment).
  All 49 tests in the file pass.

## Remaining before merge

- Live redeploy + replay of the original reported transcript against the running container,
  under the current (post-pivot) code.
- Full CPQ regression suite re-run on this branch's latest commit.
- Consider a live (non-mocked) smoke test of the Critical finding's exact scenario
  ("Quantity for Tier 2 Bundle" + "change the quantity to 2") against a real model call, since
  the shipped test only verifies the prompt's content, not a live model's actual judgment on
  it.
