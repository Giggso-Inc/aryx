# Multi-Select Blind-Pick Must Respect the Real Data-Table Whitelist — Plan

## Context

Today's fix (`CPQ_MULTISELECT_GOVERNED_NO_MATCH_ASK_PLAN_2026_08_10.md`) lets a governed,
unconstrained multi-select blind-pick `candidate_opts[0]` — the catalog's raw, first-listed menu
option — when nothing else resolves it. Live-verified against the real "APX NEXT ENHANCED"
configuration (`/andie`, 2026-08-10): for `carrierSelectionMultiSelect_astro`, the real ingested
Data Table (`resolve_whitelist_values`) already narrows the legal set to exactly 4 of the 6 raw
catalog options for this exact context (destination country `US`, `aTAKEnabledPackage_astro`
`NO`) — `ATT/FIRSTNET`, `LTE CAPABILITY NO SERVICE`, `T MOBILE`, `VERIZON`; `BELL CANADA(PROVIDED
BY MOTOROLA)` and `T MOBILE AND T SATELLITE` are real, data-proven ILLEGAL for this context. The
blind-pick's raw catalog-order first pick (`ATT/FIRSTNET`) happened to also be one of the 4 legal
values — correct, but coincidentally: the blind-pick never actually consulted the whitelist, so a
catalog whose first-listed option happened to be `BELL CANADA` would have picked a real, data-
proven-illegal value.

`_resolve_via_data_tables` already computes this exact narrowed list (via
`data_table_resolver.resolve_whitelist_values`) but only USES it when it narrows to exactly one
value (`len(values) != 1: return None`) — by design, since that function's job is "a single
confident answer or nothing." The blind-pick fallback needs the narrowed list even when it has 2+
members, to pick from real, confirmed-legal options instead of the unfiltered raw catalog menu.

## Approach

Add a small new static helper next to `_resolve_via_data_tables` (`engine.py:5696`):

```python
@staticmethod
def _resolve_narrowed_legal_values(
    vn: str, filled: dict[str, str], workspace_id: int, catalog_prefix: str = "",
    cache: dict[tuple[int, str], tuple] | None = None,
) -> list[str] | None:
    """Real ingested Data Table whitelist for `vn`, however many values it
    narrows to (unlike _resolve_via_data_tables, which only returns when
    exactly one). None -- no ingested table has any row for this attr in
    this context (genuinely unknown, not zero); [] -- real rows exist but
    none match the current filled state (confirmed zero legal values);
    [v1, v2, ...] -- the real, catalog-sourced legal set."""
    base_model = filled.get("modelSelectionbaseModel_astro", "")
    if not base_model:
        return None
    product = filled.get("productSelectionProduct_all", "")
    for cpq_model in _cpq_model_candidates(product, workspace_id, catalog_prefix, cache, base_model=base_model):
        values = dt_resolve_whitelist_values(cpq_model, base_model, vn, filled, workspace_id, catalog_prefix, cache)
        if values is not None:
            return values
    return None
```

Wire it into the blind-pick branch (`elif is_unconstrained and candidate_opts:`, the same branch
today's earlier fix made reachable with a layout loaded): before picking `candidate_opts[0]`, call
this helper (only when `workspace_id is not None`, matching every other Data Table attempt's opt-in
convention). When it returns a non-`None` list, filter `candidate_opts` down to just the entries
whose `item_value` is in that real legal set, and pick the FIRST of the **narrowed** list instead of
the raw one. Three real outcomes:

- No table coverage at all (`None`) — unchanged, raw catalog-order pick (today's behavior).
- Narrowed to 1+ real legal values — pick the first of those, still tagged
  `"default_first_available"` (unchanged tag, preserves the existing re-validation contract that
  keys on this exact tag).
- Narrowed to confirmed **zero** legal values for this exact context — correctly fall through to
  the existing empty-fallback (`filled_multi[vn] = []`) instead of guessing from the raw list at
  all; this is a real, data-proven "nothing here is legal right now," not a guess.

This is additive and narrowly scoped: it only changes the SPECIFIC blind-pick this morning's fix
introduced (reachable only when genuinely unconstrained, governed, and a layout is loaded); every
other resolution path (constraint-narrowed, recommendation-satisfied, `_resolve_via_data_tables`'s
own single-confident-match case) is untouched.

## Critical files

- `src/aryx/cpq/engine.py` — new `_resolve_narrowed_legal_values` static method; the blind-pick
  branch inside `auto_fill`'s second multi-select code path updated to use it.
- `tests/test_cpq_multiselect_autofill_overselection.py` — new tests: real Data Table narrows to
  2+ legal values → picks the first of the NARROWED set, not raw catalog order; narrows to
  confirmed zero → falls to empty, not a guess; no table coverage at all → unchanged raw-order pick
  (regression lock for today's earlier fix).

## Verification results (live, 2026-08-10)

Unit tests: 3 new tests in `tests/test_cpq_multiselect_autofill_overselection.py` (narrowed 2+
legal values → picks the first of the narrowed set, never the raw-order-first illegal option;
confirmed-zero-legal-values → falls to empty; no table coverage at all → unchanged raw-order pick).
Full `-k cpq` regression: 874 passed (up from 871), same 3 pre-existing unrelated failures.

Live verification against the real container with the complete real "APX NEXT ENHANCED" payload
(all 26 real fields): `carrierSelectionMultiSelect_astro` still resolves to `ATT/FIRSTNET` — now
confirmed via direct call to `_resolve_narrowed_legal_values` to be because it's genuinely one of
the 4 real legal values (`ATT/FIRSTNET`, `LTE CAPABILITY NO SERVICE`, `T MOBILE`, `VERIZON`) for
this exact context, with the two real, data-proven-illegal options (`BELL CANADA(PROVIDED BY
MOTOROLA)`, `T MOBILE AND T SATELLITE`) correctly excluded from ever being pickable — not
coincidence, as it was before this fix.

## Verification

1. **Unit tests**: replay the real `carrierSelectionMultiSelect_astro` shape with a synthetic
   Data Table fixture (matching the `_patch_rdb`-style convention already used in
   `test_cpq_auto_fill_data_table_tier.py`) where the raw catalog's first option is a real,
   data-proven-illegal value and the second is legal — assert the SECOND (real, narrowed) value is
   picked, not the raw-order first one. Confirmed-zero-legal-values case falls to empty. No-
   coverage-at-all case is unaffected (today's existing raw-order behavior, regression lock).
2. **Regression check**: full `-k cpq` suite — same 3 pre-existing failures only; today's earlier
   multi-select tests (both the original over-selection suite and the two new tests from this
   session) stay green.
3. **Live verification**: re-run the exact real "APX NEXT ENHANCED" scenario; confirm
   `carrierSelectionMultiSelect_astro` still resolves to `ATT/FIRSTNET` (still correct, now
   provably because it's in the real narrowed legal set, not coincidence) and spot-check via a
   direct Python call that the narrowed set genuinely excludes `BELL CANADA(PROVIDED BY MOTOROLA)`/
   `T MOBILE AND T SATELLITE` from being pickable for this real context.
4. Rebuild, redeploy, live-verify — same discipline as every fix today.
