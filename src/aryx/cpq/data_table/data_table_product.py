"""Resolves product-to-CPQModel and per-region attribute-value mappings from
ingested hierarchy-shaped and region-rule-shaped Data Table rows.

Split out of `cpq/data_table_resolver.py` (Raven Style Compliance Plan,
Phase 2a, 2026-09-03).
"""
from __future__ import annotations

from typing import Any

from aryx.cpq.data_table.data_table_loader import _load_all_tables
from aryx.cpq.data_table.data_table_shapes import _attr_val_col_pairs, _is_attr_var_mapping_shaped
from aryx.cpq.data_table.data_table_stale_models import _is_stale_cpq_model
from aryx.cpq.rdb.rdb import get_cpq_rdb


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


# Guard against a spurious substring match on a very short real product
# token (e.g. a 2-character code) matching purely by coincidence inside an
# unrelated raw sentence -- same minimum-length discipline already used by
# CpqEngine.resolve_product_hint's own Pass 2 (_HINT_MIN_PHRASE_LEN).
_HINT_MATCH_MIN_LEN = 4


def resolve_product_cpq_models_from_hint(
    hint_text: str, workspace_id: int, catalog_prefix: str = "",
    cache: dict[tuple[int, str], tuple] | None = None,
) -> tuple[str, ...]:
    """Like `resolve_product_cpq_models_from_rows`, but for free/raw text
    (e.g. a customer's own "I want APX 3000 for United States") instead of
    an already-exact product name -- breaks the chicken-and-egg gap where
    a device name is only known from what the customer originally typed,
    before `productSelectionProduct_all` itself has been answered (docs/
    Hardware_Version_APX3000_Product_Anchoring_Issue.md v2.2's merged
    recommendation, step 1).

    Reuses the SAME cached product-name -> CPQModel map `resolve_product_
    cpq_models_from_rows` already builds and memoizes (one O(constraint_
    rows) scan per (workspace_id, catalog_prefix), never repeated) --
    every real, ingested product name is checked as a case-insensitive
    substring match against `hint_text`, mirroring `resolve_product_hint`'s
    own Pass 2 matching style.

    Returns () (never guesses) when:
      - no real product name matches at all, or
      - 2+ DISTINCT real product names both match (genuinely ambiguous --
        e.g. a raw sentence long enough to coincidentally contain two real
        catalog product strings), or
      - the only match is shorter than _HINT_MATCH_MIN_LEN characters (too
        short to trust as a real, deliberate mention rather than
        coincidental overlap).

    Callers must treat an empty result exactly like an unresolvable hint --
    fall through to whatever behavior applies when the device is genuinely
    unknown, never assume it means "no real catalog data exists."
    """
    # Same product-name -> CPQModel(s) map resolve_product_cpq_models_
    # from_rows itself builds -- memoized in `cache` under the identical
    # key when a cache dict is supplied (so a caller sharing one per-turn
    # cache across both functions never pays the O(constraint_rows) scan
    # twice), but computed fresh (never persisted) when `cache` is None,
    # exactly like every other Data Table resolver in this module.
    key = ("_product_to_cpq_models", workspace_id, catalog_prefix)
    if cache is not None and key in cache:
        product_to_models: dict[str, set[str]] = cache[key]
    else:
        constraint_rows, _, _, _, _ = _load_all_tables(workspace_id, catalog_prefix, cache)
        product_to_models = {}
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
    if not product_to_models:
        return ()

    hint_norm = " ".join((hint_text or "").strip().upper().split())
    if not hint_norm:
        return ()

    matched_products: set[str] = set()
    for product_name in product_to_models:
        candidate = " ".join(product_name.split())
        if len(candidate) < _HINT_MATCH_MIN_LEN:
            continue
        if candidate in hint_norm:
            matched_products.add(product_name)

    if len(matched_products) != 1:
        return ()
    return tuple(sorted(product_to_models[next(iter(matched_products))]))


# ---------------------------------------------------------------------------
# Feature/region search (Phase 2 of the 2026-09-15/16 feature/region search
# plan). Both resolvers below are REVERSE lookups relative to the resolvers
# above them: resolve_region_allow_value answers "what value does this model
# get in this region"; search_products_by_region answers "which models allow
# this region at all". Same real, already-ingested Data Table shapes --
# confirmed in Phase2_DataTable_Schema_Audit.md, no new ingestion needed.
# ---------------------------------------------------------------------------

def _load_attr_var_mapping_rows(
    workspace_id: int, catalog_prefix: str = "",
    cache: dict[tuple, Any] | None = None,
) -> list[dict[str, Any]]:
    """Standalone scan for attrToVarMapping-shaped rows.

    Kept separate from _load_all_tables() rather than added as its 6th
    bucket there: every one of that function's existing call sites unpacks
    its return value by fixed position (e.g. `_, _, _, _, region_rule_rows
    = _load_all_tables(...)`), so adding a 6th element would break all of
    them. This duplicates _load_all_tables()'s per-ontology-type scan loop
    -- acceptable for a first version; a shared generic multi-shape scanner
    would be a reasonable follow-up once more standalone shapes accumulate.

    Uses a cache key suffixed with "attr_var_mapping" so a `cache` dict
    shared with _load_all_tables() callers cannot collide on the same
    (workspace_id, catalog_prefix) key against a differently-shaped value.
    """
    key = (workspace_id, catalog_prefix, "attr_var_mapping")
    if cache is not None and key in cache:
        return cache[key]
    rdb = get_cpq_rdb()
    rows: list[dict[str, Any]] = []
    for ontology_type in rdb.list_ontology_types(workspace_id):
        entities = rdb.fetch_entities_by_exact_type(workspace_id, ontology_type)
        for _eid, attrs in entities:
            if _is_attr_var_mapping_shaped(set(attrs.keys())):
                rows.append(attrs)
    if cache is not None:
        cache[key] = rows
    return rows


def resolve_variable_name_for_role(
    cpq_model: str, attribute_name: str, workspace_id: int,
    catalog_prefix: str = "", cache: dict[tuple, Any] | None = None,
) -> str | None:
    """The real variable_name an ingested attrToVarMapping-shaped Data Table
    (e.g. attrToVarMapping.csv -- cpqModel/group/attributeName/
    attributeVariable) gives a human-readable role/label under `cpq_model`,
    when exactly one row matches -- catalog-agnostic, detected by column
    shape, never a specific filename or per-catalog hardcoding.

    Confirmed real (2026-09-15 hardcoding audit): APX1000/"Feature Type"
    resolves to systemEnhancementFeatureType_astro; APX1000/"Region" to
    modelSelectionRegion_astro; APX1000/"Base Model" to
    modelSelectionbaseModel_astro.

    Returns None when zero rows match this exact (cpq_model, attribute_name)
    pair, or when 2+ DISTINCT variable names exist (a genuine tie -- never
    guesses across one), matching resolve_region_allow_value's own
    never-guess convention.
    """
    rows = _load_attr_var_mapping_rows(workspace_id, catalog_prefix, cache)
    norm_model = (cpq_model or "").strip().upper()
    norm_role = (attribute_name or "").strip().casefold()

    matches: set[str] = set()
    for row in rows:
        if str(row.get("cpqModel") or "").strip().upper() != norm_model:
            continue
        if str(row.get("attributeName") or "").strip().casefold() != norm_role:
            continue
        var_name = row.get("attributeVariable")
        if var_name:
            matches.add(str(var_name).strip())

    if len(matches) != 1:
        return None
    return next(iter(matches))


def search_products_by_region(
    region: str, workspace_id: int, catalog_prefix: str = "",
    cache: dict[tuple[int, str], tuple] | None = None,
) -> list[dict[str, Any]]:
    """Every real ALLOW rule row for `region`, across all models/attributes
    -- "which products/models allow region=X", the reverse direction from
    resolve_region_allow_value's "what value does model Y get in region X".

    Same ingested region-rule-shaped rows (model/value/region/ruleType/
    attribute[/UDCC]) resolve_region_allow_value already reads via
    _load_all_tables() -- no new Data Table shape or ingestion needed.

    Returns one dict per distinct (model, attribute, value) triple matching
    `region` with ruleType=ALLOW -- deduplicated, since the same triple can
    legitimately appear on more than one row (e.g. a region row plus a
    country-scoped override row for the same allowed value).
    """
    _, _, _, _, region_rule_rows = _load_all_tables(workspace_id, catalog_prefix, cache)
    norm_region = (region or "").strip().upper()

    seen: set[tuple[Any, Any, Any]] = set()
    results: list[dict[str, Any]] = []
    for row in region_rule_rows:
        if str(row.get("ruleType") or "").strip().upper() != "ALLOW":
            continue
        if str(row.get("region") or "").strip().upper() != norm_region:
            continue
        model = row.get("model")
        attribute = row.get("attribute")
        value = row.get("value")
        triple = (model, attribute, value)
        if triple in seen:
            continue
        seen.add(triple)
        results.append({
            "model": model, "attribute": attribute, "value": value,
            "region": row.get("region"),
        })
    return results


def search_products_by_feature(
    feature_label: str, feature_value: str, workspace_id: int,
    cpq_model: str | None = None, catalog_prefix: str = "",
    cache: dict[tuple, Any] | None = None,
) -> list[dict[str, Any]]:
    """Every real constraint-shaped row whose value for `feature_label`
    (a human label, e.g. "Feature Type") contains `feature_value` -- "which
    products have feature X", the reverse direction from
    resolve_whitelist_values's "what values are legal for this model's
    attribute".

    Features have no dedicated Data Table shape (confirmed in
    Phase2_DataTable_Schema_Audit.md) -- they're rows in the same general
    constraint-shaped table (CPQModel/BaseModel/attrN/valN) every other
    constraint resolver in this module already reads, keyed by variable
    name rather than the human label callers actually have. This resolves
    `feature_label` to its real variable_name per model via
    resolve_variable_name_for_role() first (the mapping is per-model, since
    two models can use different variable names for the same labeled role),
    then scans that model's constraint rows for a matching attrN/valN pair.

    `cpq_model`, when given, scopes the search to just that model (cheaper,
    and avoids resolving the label separately for every other ingested
    model). Left as None, every distinct CPQModel among the ingested
    constraint rows is tried.

    Case-insensitive substring match on the value (CONTAINS semantics,
    matching find_entities(attrs=...)'s own convention on the graph side),
    not exact-equality -- a caller searching "Encryption" should match a
    real value like "AES-256 Encryption" too.
    """
    constraint_rows, _, _, _, _ = _load_all_tables(workspace_id, catalog_prefix, cache)
    norm_value = (feature_value or "").strip().casefold()
    norm_model_filter = (cpq_model or "").strip().upper() or None

    var_name_by_model: dict[str, str | None] = {}
    results: list[dict[str, Any]] = []
    for row in constraint_rows:
        model = row.get("CPQModel")
        norm_model = str(model or "").strip().upper()
        if norm_model_filter is not None and norm_model != norm_model_filter:
            continue
        if norm_model not in var_name_by_model:
            var_name_by_model[norm_model] = resolve_variable_name_for_role(
                model, feature_label, workspace_id, catalog_prefix, cache,
            )
        attr_var_name = var_name_by_model[norm_model]
        if not attr_var_name:
            continue
        for attr_col, val_col in _attr_val_col_pairs(set(row.keys())):
            if row.get(attr_col) != attr_var_name:
                continue
            raw_val = row.get(val_col)
            if norm_value and norm_value not in str(raw_val or "").strip().casefold():
                continue
            results.append({
                "model": model, "base_model": row.get("BaseModel"),
                "attribute": attr_var_name, "value": raw_val,
            })
    return results
