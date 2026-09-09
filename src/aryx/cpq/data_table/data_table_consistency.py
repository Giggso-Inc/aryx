"""Detects self-contradictory filled-attribute combinations, proven against
real ingested Data Table rows rather than the always-empty static
master-string attributes; also discovers supplementary CPQModel candidates
for a base model.

Split out of `cpq/data_table_resolver.py` (Raven Style Compliance Plan,
Phase 2a, 2026-09-03).
"""
from __future__ import annotations

from aryx.cpq.data_table.data_table_loader import _load_all_tables
from aryx.cpq.data_table.data_table_stale_models import _is_stale_cpq_model


def discover_cpq_models_for_base_model(
    base_model: str, workspace_id: int, catalog_prefix: str = "",
    cache: dict[tuple[int, str], tuple] | None = None,
) -> list[str]:
    """Every CPQModel code any ingested constraint- or sequence-shaped Data
    Table row actually uses for this EXACT `base_model` (never "ALL" --
    those are catalog-wide defaults, not evidence a given CPQModel code
    covers this specific base model).

    A product's own CPQModel mapping (engine._cpq_model_candidates, driven
    by a hand-verified override map or the coarser CPQModelHierarchy
    fallback) is the primary, most-accurate source -- but confirmed live
    (2026-08-08) a single real base model can appear under a MORE SPECIFIC
    variant code than that mapping produces (e.g. a "APX NEXT Single Band"
    product's base model H45TGU9PW8AN has its real attrSequence/whitelist
    rows keyed to "APXNEXTXNSINGLE", not the "APXNEXTSINGLE" the product
    name maps to) -- a genuine cross-SKU base-model-sharing case in the
    source catalog, not a resolver bug. This is a SUPPLEMENTARY discovery
    source: callers should try the product-derived candidates FIRST (still
    the most accurate for the common case) and append these as additional
    candidates, never replacing them.
    """
    constraint_rows, sequence_rows, _, _, _ = _load_all_tables(workspace_id, catalog_prefix, cache)
    found: set[str] = set()
    for row in constraint_rows:
        if row.get("BaseModel") == base_model:
            cm = row.get("CPQModel")
            if cm and not _is_stale_cpq_model(cm):
                found.add(cm)
    for row in sequence_rows:
        if row.get("BaseModel") == base_model:
            cm = row.get("CPQModel")
            if cm and not _is_stale_cpq_model(cm):
                found.add(cm)
    return sorted(found)


def find_inconsistent_filled_pairs_detailed(
    cpq_model: str, base_model: str, filled: dict[str, str],
    workspace_id: int, catalog_prefix: str = "",
    cache: dict[tuple[int, str], tuple] | None = None,
) -> set[tuple[str, str]]:
    """Same real-data-proven-contradiction detection as
    `find_inconsistent_filled_pairs`, but returns the actual invalid
    `(attr_a, attr_b)` pairs instead of a flattened set of variable names --
    needed by callers that must name BOTH sides of a conflict (e.g. a re-ask
    message), not just know which variables are involved.

    docs/CPQ_TURN_LATENCY_PERFORMANCE_PLAN_2026_08_19.md (RC3, 2026-08-24):
    a filled (attr, value) is never penalized by a narrow pairing row when
    that EXACT value also has its own standalone row (a row where its
    partner side is `None`, proving it's independently valid regardless of
    any second attribute). Live-confirmed bug:
    `additionalSystemEnhancementFeatureType_astro` has 4 legitimate
    standalone values plus one narrow exception row pairing a DIFFERENT
    value with `ultimateDestinationCountry` ("DELETE NARROWBANDING-WAIVER
    REQUIRED", "US") -- a specific waiver SKU, not a general rule. Without
    this check, once country is filled, that one exception row was wrongly
    treated as the pair's ENTIRE truth table, so any of the 4 unrelated
    standalone values got flagged inconsistent forever. Deliberately scoped
    to the VALUE, not the whole attribute: filling the exception row's own
    value (`DELETE NARROWBANDING-WAIVER REQUIRED`) with a mismatching
    country is still a real, data-proven contradiction and must still be
    caught -- that value has no standalone row of its own to exempt it.
    Real exhaustive pairs (e.g. modelSelectionFrequencyBands_astro/
    modelSelectionFrequencyBandPlus_astro) have no standalone rows for
    either side's values, so this check never affects them.
    """
    constraint_rows, _, _, _, _ = _load_all_tables(workspace_id, catalog_prefix, cache)
    scoped = [
        r for r in constraint_rows
        if r.get("CPQModel") == cpq_model and r.get("BaseModel") in (base_model, "ALL")
    ]
    standalone_values = {
        (r.get("attr1"), r.get("val1")) for r in scoped
        if r.get("attr1") and r.get("val1") and not r.get("attr2")
    } | {
        (r.get("attr2"), r.get("val2")) for r in scoped
        if r.get("attr2") and r.get("val2") and not r.get("attr1")
    }
    linked_pairs: set[tuple[str, str]] = set()
    for row in scoped:
        a1, a2 = row.get("attr1"), row.get("attr2")
        if a1 and a2 and a1 in filled and a2 in filled:
            linked_pairs.add((a1, a2))

    invalid_pairs: set[tuple[str, str]] = set()
    for attr_a, attr_b in linked_pairs:
        val_a, val_b = filled.get(attr_a), filled.get(attr_b)
        if (attr_a, val_a) in standalone_values or (attr_b, val_b) in standalone_values:
            continue
        matches = any(
            (row.get("attr1") == attr_a and row.get("val1") == val_a
             and row.get("attr2") == attr_b and row.get("val2") == val_b)
            or (row.get("attr1") == attr_b and row.get("val1") == val_b
                and row.get("attr2") == attr_a and row.get("val2") == val_a)
            for row in scoped
        )
        if not matches:
            invalid_pairs.add((attr_a, attr_b))
    return invalid_pairs


def find_inconsistent_filled_pairs(
    cpq_model: str, base_model: str, filled: dict[str, str],
    workspace_id: int, catalog_prefix: str = "",
    cache: dict[tuple[int, str], tuple] | None = None,
) -> set[str]:
    """Variable names among the CURRENTLY FILLED attributes whose combined
    values don't match any real ingested constraint-shaped row, for a pair
    the real data itself links together.

    Confirmed live (2026-08-08): modelSelectionFrequencyBands_astro and
    modelSelectionFrequencyBandPlus_astro -- auto-filled independently --
    landed on the SAME band for both ("700/800 MHZ" / "700/800 MHZ +"),
    while every one of 21 real ingested rows for this CPQModel pairs Bands
    with a DIFFERENT band than BandPlus. Two attributes resolved
    independently can each be individually legal in isolation while their
    COMBINATION is one the real catalog never allows.

    Linked pairs are discovered directly from the ingested rows' own
    attr1/attr2 co-occurrence -- never a hardcoded attribute-name pair.
    Only ever flags a pair when a real row proves the two ARE linked (both
    show up together in at least one row) but never with this exact
    combination -- a confident contradiction, not a guess from missing
    data. A pair with no real row linking them at all is left alone.
    """
    invalid_pairs = find_inconsistent_filled_pairs_detailed(
        cpq_model, base_model, filled, workspace_id, catalog_prefix, cache,
    )
    invalid: set[str] = set()
    for attr_a, attr_b in invalid_pairs:
        invalid.add(attr_a)
        invalid.add(attr_b)
    return invalid
