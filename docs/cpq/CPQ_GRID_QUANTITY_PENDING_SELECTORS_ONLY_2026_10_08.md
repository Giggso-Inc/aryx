# Grid quantities only for a selector the pass left pending (APX N30)

Date: 2026-10-08. Flag (off by default): `cpq_grid_quantity_pending_selectors_only_enabled`
(`ARYX_CPQ_GRID_QUANTITY_PENDING_SELECTORS_ONLY_ENABLED`).

## Problem (live, ws 1267, after #475 with all five flags on)

"I want to quote APX N30 for US" ended with `hiddenConventionalOptionsMaxQuantityAry_astro` "Please provide a value."

Log evidence: model resolved to `APXN30`, rule scope filtered (6,777 -> 1,323 hiding rules), `filled_count` 7, `pending_after_autofill` **0**,
then `ask.recompute.grid_diff` `GRID_QUANTITY_APPEND`: `removed: []`, `added`: 7 quantity holders. The not-applicable guard had left
`hiddenConventionalOptionsMaxQuantityAry_astro` open (`TIER0_NOT_APPLICABLE_GUARD`).

## Cause

`resolve_pending_grid_quantities` treats a grid selector with no selection at all as "every linked option is pending its quantity".
`append_pending_grid_quantities` calls it for every selector in the catalog, whether or not the pass left that selector pending, so
selectors the engine had decided are not applicable for the model came back as 7 quantity questions after auto-fill finished.

## Change

`append.py`: with the flag on and no explicit `selector_vns`, only selectors that were in `pending` before the call, or already hold
a selection (`filled_multi` / `filled`), are seeded. A caller naming one selector (label collision) is unchanged. Flag off: unchanged.

## Rollout / limits

Enable on dev, replay "quote APX N30 / N50 / 900 / 4500 for US": expect 0 grid questions for selectors never pending. A selector that
should be asked but is not in `pending` (a caller that builds `pending` without it) would no longer be seeded: replay is the guard.
Tests: 5 new (`tests/test_cpq_grid_quantity_pending_selectors_only_2026_10_08.py`); 2 existing grid-quantity files do not finish
within 40 s locally (database-connecting tests, not touched by this change).
