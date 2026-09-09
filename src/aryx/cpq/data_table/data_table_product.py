"""Resolves product-to-CPQModel and per-region attribute-value mappings from
ingested hierarchy-shaped and region-rule-shaped Data Table rows.

Split out of `cpq/data_table_resolver.py` (Raven Style Compliance Plan,
Phase 2a, 2026-09-03).
"""
from __future__ import annotations

from aryx.cpq.data_table.data_table_loader import _load_all_tables
from aryx.cpq.data_table.data_table_stale_models import _is_stale_cpq_model


def resolve_region_allow_value(
    attr_var_name: str, cpq_model: str, region: str, workspace_id: int,
    catalog_prefix: str = "", cache: dict[tuple[int, str], tuple] | None = None,
    country: str = "",
) -> str | None:
    """The single real per-region (optionally per-country) value an ingested
    region-rule-shaped Data Table (e.g. NewCountryRegMapping.csv --
    model/value/region/ruleType/attribute[/UDCC]) gives `attr_var_name`
    under `cpq_model`/`region`, when exactly one `ruleType=ALLOW` row
    matches -- catalog-agnostic, detected by column shape, never a specific
    filename or per-catalog hardcoding.

    Confirmed live (2026-08-10): APXNEXTSINGLE/region=NA resolves
    modelSelectionbaseModel_astro to exactly one ALLOW value
    (H45TGT9PW8AN) this way -- the same real per-region default Oracle
    CPQ's own "Set Base Model" recommendation rules try to compute at
    runtime via `Oracle_BomItemMap` (a live table never present in any
    export seen so far, see `resolve_product_cpq_models_from_rows`'s
    sibling gap for the same missing-table pattern). This static table
    independently carries the equivalent resolved answer without needing
    that missing runtime table -- not a blind guess, a real ingested
    default.

    Priority: an exact `country` match (the `UDCC` column), when supplied
    and present, wins over the coarser region-level rows -- a real
    per-country override is more specific than the region default it sits
    under. Returns None when zero ALLOW rows match this exact scope, or
    when 2+ DISTINCT allowed values exist (a genuine tie -- never guesses
    across one), so callers can safely fall through to asking instead.
    """
    _, _, _, _, region_rule_rows = _load_all_tables(workspace_id, catalog_prefix, cache)
    norm_model = (cpq_model or "").strip().upper()
    norm_region = (region or "").strip().upper()
    norm_country = (country or "").strip().upper()

    country_values: set[str] = set()
    region_values: set[str] = set()
    for row in region_rule_rows:
        if row.get("attribute") != attr_var_name:
            continue
        if str(row.get("model") or "").strip().upper() != norm_model:
            continue
        if str(row.get("ruleType") or "").strip().upper() != "ALLOW":
            continue
        value = row.get("value")
        if not value:
            continue
        row_region = str(row.get("region") or "").strip().upper()
        if row_region != norm_region:
            continue
        row_country = str(row.get("UDCC") or "").strip().upper()
        if norm_country and row_country == norm_country:
            country_values.add(value)
        elif not row_country:
            region_values.add(value)

    if norm_country and len(country_values) == 1:
        return next(iter(country_values))
    if len(region_values) == 1:
        return next(iter(region_values))
    return None


def resolve_product_cpq_model_family(
    product_name: str, workspace_id: int, catalog_prefix: str = "",
    cache: dict[tuple[int, str], tuple] | None = None,
) -> str | None:
    """The CPQModel product-FAMILY code for `product_name`, from every
    ingested hierarchy-shaped Data Table (e.g. CPQModelHierarchy.csv) in
    this workspace. Coarser than the per-product CPQModel value
    `resolve_whitelist_values` needs (e.g. returns "APXNEXT" for both "APX
    NEXT MULTI" and "APX NEXT ENHANCED", where the real whitelist rows for
    the latter are keyed "APXNEXTENHANCED") -- intended as a fallback
    candidate for products with no hand-verified entry in the caller's own
    specific map, not a full replacement for one. Returns None when no
    hierarchy table has this product at all.
    """
    _, _, hierarchy_rows, _, _ = _load_all_tables(workspace_id, catalog_prefix, cache)
    norm = (product_name or "").strip().upper()
    for row in hierarchy_rows:
        if str(row.get("Product") or "").strip().upper() == norm:
            family = row.get("cpqModelName")
            if family:
                return family
    return None


def resolve_product_cpq_models_from_rows(
    product_name: str, workspace_id: int, catalog_prefix: str = "",
    cache: dict[tuple[int, str], tuple] | None = None,
) -> tuple[str, ...]:
    """The exact, real CPQModel code(s) a constraint-shaped Data Table row
    proves this `product_name` actually uses -- derived directly from the
    ingested rows themselves, never a hand-maintained per-catalog map.

    Finer-grained than `resolve_product_cpq_model_family` (which only has
    the coarse product-FAMILY code from the hierarchy table): a real
    constraint row's own attrN/valN pair naming productSelectionProduct_all
    proves its CPQModel is one this exact product genuinely resolves to
    (confirmed live, 2026-08-09: "APX NEXT SINGLE BAND" and "APX NEXT XN
    SINGLE BAND" are distinct real products whose own rows require
    different CPQModels -- APXNEXTSINGLE vs APXNEXTXNSINGLE -- even though
    CPQModelHierarchy.csv collapses both under the same family code
    "APXNEXT"). This is the data-driven replacement for what used to be a
    hand-authored per-catalog override map (`_PRODUCT_TO_CPQ_MODEL` in
    engine.py, removed 2026-08-10) -- explicit instruction: any catalog
    needing this fine-grained split must get it from real ingested rows,
    never a new hardcoded entry for that one catalog. Catalog-agnostic:
    identical logic for every ingested catalog.

    The full product->CPQModel(s) map is memoized once per (workspace_id,
    catalog_prefix) in `cache` (same convention as
    `attr_ever_governed_for_cpq_model`'s memoization) -- a one-time
    O(constraint_rows) scan, never repeated per product name. Stale/deleted
    CPQModel codes (see `_is_stale_cpq_model`) are excluded. Returns ()
    when no constraint row anywhere names this exact product string.
    """
    key = ("_product_to_cpq_models", workspace_id, catalog_prefix)
    if cache is not None and key in cache:
        product_to_models = cache[key]
    else:
        constraint_rows, _, _, _, _ = _load_all_tables(workspace_id, catalog_prefix, cache)
        product_to_models: dict[str, set[str]] = {}
        for row in constraint_rows:
            cm = row.get("CPQModel")
            if not cm or _is_stale_cpq_model(cm):
                continue
            for i in range(1, 20):
                if row.get(f"attr{i}") == "productSelectionProduct_all":
                    val = row.get(f"val{i}")
                    if val:
                        product_to_models.setdefault(
                            str(val).strip().upper(), set(),
                        ).add(cm)
                    break
        if cache is not None:
            cache[key] = product_to_models
    norm = (product_name or "").strip().upper()
    return tuple(sorted(product_to_models.get(norm, ())))
