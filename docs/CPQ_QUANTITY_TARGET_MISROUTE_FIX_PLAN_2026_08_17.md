# CPQ Quantity Target Misroute — Fix Plan

**Date:** 2026-08-17
**Branch:** `fix/cpq-quantity-target-misroute` (from `dev-rv-msi` @ `ab1f477`, post PR #205)
**Status:** Implemented, unit-tested (52/52 passing in `test_cpq_session_product_quantity.py`); live redeploy/replay not yet done
**Severity:** High

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

## Fix design

A naive fix (require `filled_source == "user"` to even become a candidate) was considered
and rejected during planning: it would also exclude a candidate the customer explicitly
*names* in the same message (e.g. "change the VX650 item type quantity to 5"), silently
misrouting the opposite way if that attribute was only ever cascade-filled.

Revised, three-branch resolution, replacing the current LLM confident-auto-resolve step:

1. **Explicit item-name match** — if the message text names a specific catalog item, resolve
   directly to that item. Not a guess; the customer stated it. (Reuses existing catalog
   hint/label-matching machinery already used elsewhere in this file — no new mechanism.)
2. **Generic reference + a real `user`-sourced candidate exists** — genuinely ambiguous;
   ask the existing clarifying question (`ask_api.py:7642-7660` already has this path — it
   becomes the only way an ambiguous case is resolved, not an LLM fallback after a guess).
3. **Generic reference + no `user`-sourced candidate** — unambiguous; resolve straight to the
   overall product quantity, no question, no LLM call.

This removes the LLM's silent auto-resolve step for the ambiguous branch entirely. The only
remaining LLM/pattern involvement is step 1's name-matching, which is a lookup, not a guess.

## Why this direction over alternatives

- **Always ask, regardless of provenance:** rejected — would add a clarifying question to the
  overwhelming common case (a bare "change the quantity" turn with no genuine per-item
  quantity ever set by the customer), which is the majority of real traffic.
- **Keep the LLM auto-resolve, just add context to its prompt:** considered as a
  defense-in-depth layer, but superseded once the provenance distinction showed that real
  ambiguity is rare enough to just ask outright — fewer moving parts, zero silent-misroute
  risk.

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

## Implementation

- `src/aryx/cpq/engine.py` — added `question_names_quantity_attr(question, attr)`: strips
  quantity-boilerplate words from the candidate's display label, then requires the
  distinctive remainder to appear in the question (a digit-bearing token, e.g. "vx650", is
  trusted alone; otherwise every remaining word must appear — same never-guess-off-one-word
  convention `extract_catalog_hints` already uses elsewhere in this file).
- `src/aryx/api/ask_api.py` — replaced the `_qty_candidates`/`_llm_resolve_quantity_target()`
  block (was ~7579-7592) with the three-branch deterministic resolution: explicit name match
  wins outright; otherwise only `filled_source == "user"` candidates may compete with the
  overall product quantity; no competing candidate resolves straight to product. Removed
  `_llm_resolve_quantity_target()` entirely (its only call site) along with the stale
  docstring references to it in `engine.py`.
- `tests/test_cpq_session_product_quantity.py` — added `question_names_quantity_attr` unit
  tests, added `test_cascade_filled_attribute_never_competes_with_bare_quantity_reference`
  (the actual reported bug, now fixed) and
  `test_explicit_named_attribute_wins_even_when_only_cascade_sourced` (the naive-fix
  regression this design specifically avoids), updated the two existing disambiguation tests
  to set `filled_source == "user"` (the discriminator the fix introduces), and removed the
  now-obsolete `_llm_resolve_quantity_target` direct unit test. All 52 tests in the file pass.

## Remaining before merge

- Live redeploy + replay of the original reported transcript against the running container
  has not been done this session (deferred to avoid disrupting the container while other
  work was in flight) — recommended before closing this out.
- Full CPQ regression suite re-run on this branch.
