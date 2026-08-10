"""Resolves constraint/sibling-manifest data from real Oracle CPQ Data Table
exports, not the master-string attributes that are always empty in a static
Rules/Attributes ("Download Configuration") export -- see docs/CPQ_CARRIER_
WIRELESS_FREQBAND_DATA_GAP_PROOF_2026_08_07.md §11-§12 for how `whitelist`
and `attrSequence` were identified and cross-validated against a real Oracle
CPQ admin trace page and a live Pipeline Viewer capture.

Reads from Aryx's real ingested entity store (aryx_entity via
aryx.cpq.rdb.get_cpq_rdb()), NOT from any bundled/hardcoded CSV file --
whichever Data Table CSVs a user uploads through the normal ingestion UI
(same CsvConnector path as any other tabular upload) are what this module
sees. There is no fixed file list, no per-product data file, and nothing
here needs updating when a new catalog's own Data Table CSV is ingested.

Generalized by TABLE SHAPE, not table name or product family. Every real
Data Table export seen so far is one of two column signatures, regardless
of what the table is actually called or what ontology_type ingestion gave
it (a generic PascalCase derivation of the filename, see
aryx.pipeline.doc_discovery._stem_type -- never a literal "whitelist"/
"attrSequence" string):

  "constraint"-shaped  -- CPQModel, BaseModel, attr1/val1 [, attr2/val2 ...]
                          (the source of hiddenConstraintMasterString_astro).
                          Column COUNT for the attrN/valN pairs varies by
                          export -- detected from the ingested attributes'
                          own keys, not hardcoded.
  "sequence"-shaped     -- CPQModel, BaseModel, AttrName, Seq[, optionOrReqFlag]
                          (the source of hiddenMasterStringForAstroPortable_astro).
  "hierarchy"-shaped    -- Product, cpqModelName[, productFamily, productLine,
                          ...] (the source of the Product -> CPQModel-family
                          mapping, e.g. CPQModelHierarchy.csv). NOTE this maps
                          a product name to its coarse product-FAMILY code
                          only (e.g. "APX NEXT ENHANCED" -> "APXNEXT", not
                          "APXNEXTENHANCED") -- real per-product refinement
                          beyond the family is BML-script-derived business
                          logic, not present in this reference table. Used
                          here only as a fallback for products with no
                          constraint-row coverage in
                          `resolve_product_cpq_models_from_rows` (the
                          data-driven, catalog-agnostic per-product
                          resolver), never to override it.
  "region_rule"-shaped  -- model, value, region, ruleType, attribute[, UDCC]
                          (e.g. NewCountryRegMapping.csv) -- per-(CPQModel,
                          region[, country]) ALLOW/DISALLOW rows for a named
                          attribute. Confirmed live (2026-08-10): this is a
                          real, non-hardcoded resolution path for attributes
                          Oracle CPQ's own script-based recommendation rules
                          otherwise compute at runtime against a live table
                          this repo never has ingested (e.g. Base Model's
                          "Set Base Model" rules query `Oracle_BomItemMap`,
                          absent from every export seen so far) -- this
                          static table independently carries the same
                          resolved answer. See `resolve_region_allow_value`.

A new rule referencing a never-seen-before table needs zero new code here
IF its ingested rows match one of these four shapes -- only a genuinely new
column signature needs a new detector, added to `_SHAPE_DETECTORS` below.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from aryx.cpq.rdb import get_cpq_rdb

logger = logging.getLogger(__name__)

# Module-level, short-TTL cache for _load_all_tables, keyed by (workspace_id,
# catalog_prefix). Mirrors engine.py's _LAYOUT_COMPONENTS_CACHE pattern.
# Needed because ask_api.py calls evaluate_rules_loop (and therefore
# _load_all_tables) multiple times per single /ask HTTP request, each with
# its own fresh per-call `cache` dict -- confirmed live against workspace 43
# (56,357 constraint rows, 46,865 sequence rows): 6+ consecutive full-table
# rescans (14-27s each) for the identical key within one turn. A short TTL
# (rather than pure process-lifetime) keeps this safe against a Data Table
# CSV being re-ingested mid-session.
_TABLES_CACHE: dict[tuple[int, str], tuple[float, tuple]] = {}
_TABLES_CACHE_TTL_SECONDS = 30.0


def _clear_tables_cache() -> None:
    """Test-isolation hook -- call from an autouse fixture to prevent this
    process-lifetime cache from leaking fake/monkeypatched rows between
    tests that reuse the same (workspace_id, catalog_prefix) key."""
    _TABLES_CACHE.clear()


# ---------------------------------------------------------------------------
# Shape detection -- classify an ingested entity type by the KEYS its rows'
# JSONB attributes actually have, not by its ontology_type name.
# ---------------------------------------------------------------------------


def _is_constraint_shaped(keys: set[str]) -> bool:
    return (
        "CPQModel" in keys and "BaseModel" in keys
        and "attr1" in keys and "val1" in keys
    )


def _is_sequence_shaped(keys: set[str]) -> bool:
    return (
        "CPQModel" in keys and "BaseModel" in keys
        and "AttrName" in keys and "Seq" in keys
    )


def _is_hierarchy_shaped(keys: set[str]) -> bool:
    return "Product" in keys and "cpqModelName" in keys


def _is_series_mapping_shaped(keys: set[str]) -> bool:
    # e.g. Seriesmodelsmapping.csv -- maps a (region, country, ...)
    # condition to the real CPQModel variant that actually applies,
    # keyed by attrN/opN/valN condition triples rather than a bare
    # attrN/valN pair (constraint-shaped tables have no opN column and
    # no childCPQModel). Disjoint from every other shape's required keys
    # (no CPQModel/BaseModel/Product/cpqModelName here), so detection
    # order relative to the others doesn't matter.
    return "childCPQModel" in keys and "attr1" in keys and "val1" in keys and "op1" in keys


def _is_region_rule_shaped(keys: set[str]) -> bool:
    # e.g. NewCountryRegMapping.csv -- a per-(CPQModel, region[, country])
    # ALLOW/DISALLOW rule for a single named attribute + value. Disjoint
    # from every other shape's required keys (no CPQModel/BaseModel/attr1/
    # val1/AttrName/Seq/Product/cpqModelName/childCPQModel here), so
    # detection order relative to the others doesn't matter.
    return {"model", "value", "region", "ruleType", "attribute"} <= keys


# Ordered so a more specific shape (sequence) is checked before a more
# general one, in case a future table's keys could satisfy both.
_SHAPE_DETECTORS: tuple[tuple[str, "callable"], ...] = (
    ("sequence", _is_sequence_shaped),
    ("series_mapping", _is_series_mapping_shaped),
    ("region_rule", _is_region_rule_shaped),
    ("constraint", _is_constraint_shaped),
    ("hierarchy", _is_hierarchy_shaped),
)


def _detect_shape(keys: set[str]) -> str | None:
    for shape_name, detector in _SHAPE_DETECTORS:
        if detector(keys):
            return shape_name
    return None


def _attr_val_col_pairs(keys: set[str]) -> list[tuple[str, str]]:
    """Every attrN/valN pair actually present in a constraint-shaped row's
    keys, in order -- N is discovered, never assumed to be a fixed count."""
    pairs = []
    n = 1
    while f"attr{n}" in keys and f"val{n}" in keys:
        pairs.append((f"attr{n}", f"val{n}"))
        n += 1
    return pairs


def _attr_op_val_triples(keys: set[str]) -> list[tuple[str, str, str]]:
    """Every attrN/opN/valN column-name triple present in a series-mapping-
    shaped row's keys, in order -- N discovered, never a fixed count."""
    triples = []
    n = 1
    while f"attr{n}" in keys and f"op{n}" in keys and f"val{n}" in keys:
        triples.append((f"attr{n}", f"op{n}", f"val{n}"))
        n += 1
    return triples


def _normalize_label(text: str) -> str:
    """Case/whitespace/trademark-symbol-insensitive comparison key -- a real
    catalog's own childCPQModelLabel carries a "™" a menu item's item_text
    doesn't (confirmed live: "APX NEXT™ International (Federal)" vs "APX
    NEXT International (Federal)")."""
    stripped = "".join(ch for ch in text if ch not in "™®©")
    return " ".join(stripped.split()).strip().casefold()


def _load_all_tables(
    workspace_id: int, catalog_prefix: str = "",
    cache: dict[tuple[int, str], tuple] | None = None,
) -> tuple[
    list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]],
    list[dict[str, Any]],
]:
    """Query aryx_entity for every ingested entity type in this workspace,
    classify EVERY ROW by shape individually, and return
    (constraint_rows, sequence_rows, hierarchy_rows, series_mapping_rows,
    region_rule_rows) -- flat lists of {column: value} dicts pooled across
    every matching
    ingested table, whatever it's called.

    Two live-discovered bugs fixed here (confirmed against a real 453K-
    entity workspace with 72 ingested types):

    1. Fetches by EXACT ontology_type (fetch_entities_by_exact_type), not
       the LIKE-suffix fetch_entities_by_type. Two real ingested types can
       share a suffix -- "Whitelist" and "Advancedwhitelist" both end in
       "whitelist" -- so the suffix match for one silently pulled in the
       other's differently-shaped rows too, corrupting the pool.
    2. Classifies EACH ROW's shape independently, not the whole type from
       a single sample row. Real CSV rows can be sparse -- a row whose
       "Product" cell was empty in the source has no "Product" key stored
       at all -- so checking only entities[0] risks misclassifying (and
       silently dropping) an entire otherwise-valid type whenever its
       first-returned row (Postgres gives no ordering guarantee) happens
       to be a sparse or differently-shaped outlier. Confirmed live: a
       3,138-row CPQModelHierarchy-shaped type was entirely skipped this
       way because one row lacked "Product".

    catalog_prefix is accepted for interface consistency with the rest of
    the CPQ engine's workspace-scoping convention, but doesn't affect
    exact-type lookups here -- CSV-derived ontology_types never carry a
    catalog_prefix the way XML-derived rule/attr types do (see
    aryx.pipeline.doc_discovery._stem_type), so there is nothing for it to
    filter on for Data Tables specifically.

    `cache`, when passed, is a plain dict the CALLER owns (typically for the
    lifetime of one auto_fill/evaluate_rules_loop pass) -- this function
    reuses a prior scan for the same (workspace_id, catalog_prefix) instead
    of re-querying, and also populates it from the module-level cache below
    when possible. Without it (default), the module-level cache is still
    consulted first.

    Beneath the per-call `cache`, a MODULE-LEVEL short-TTL cache
    (`_TABLES_CACHE`) also keys on (workspace_id, catalog_prefix) and
    survives across separate top-level calls -- confirmed live against a
    453K-entity, 72-ingested-type workspace: a single /ask HTTP request
    calls evaluate_rules_loop (and therefore this function) roughly 8 times,
    each with its own fresh per-call `cache` dict, so the per-call cache
    alone still repeated the full ~15-27s scan every time within one turn.
    The module-level cache collapses that to one scan per TTL window
    regardless of how many separate per-call caches are in play.
    """
    if cache is not None:
        key = (workspace_id, catalog_prefix)
        if key in cache:
            logger.info("cpq_perf: _load_all_tables CACHE HIT (call-local) ws=%s prefix=%r", workspace_id, catalog_prefix)
            return cache[key]

    _mod_key = (workspace_id, catalog_prefix)
    _mod_hit = _TABLES_CACHE.get(_mod_key)
    if _mod_hit is not None:
        _mod_ts, _mod_result = _mod_hit
        if time.monotonic() - _mod_ts < _TABLES_CACHE_TTL_SECONDS:
            logger.info("cpq_perf: _load_all_tables CACHE HIT (module) ws=%s prefix=%r", workspace_id, catalog_prefix)
            if cache is not None:
                cache[_mod_key] = _mod_result
            return _mod_result

    _t0 = time.monotonic()
    rdb = get_cpq_rdb()
    constraint_rows: list[dict[str, Any]] = []
    sequence_rows: list[dict[str, Any]] = []
    hierarchy_rows: list[dict[str, Any]] = []
    series_mapping_rows: list[dict[str, Any]] = []
    region_rule_rows: list[dict[str, Any]] = []
    _bucket = {
        "constraint": constraint_rows,
        "sequence": sequence_rows,
        "hierarchy": hierarchy_rows,
        "series_mapping": series_mapping_rows,
        "region_rule": region_rule_rows,
    }

    for ontology_type in rdb.list_ontology_types(workspace_id):
        entities = rdb.fetch_entities_by_exact_type(workspace_id, ontology_type)
        if not entities:
            continue
        counts = {"constraint": 0, "sequence": 0, "hierarchy": 0, "series_mapping": 0, "region_rule": 0, None: 0}
        for _eid, attrs in entities:
            shape = _detect_shape(set(attrs.keys()))
            counts[shape] += 1
            if shape is not None:
                _bucket[shape].append(attrs)
        logger.debug(
            "data_table_resolver: %s (%d rows) -- constraint=%d sequence=%d "
            "hierarchy=%d series_mapping=%d region_rule=%d unrecognized=%d",
            ontology_type, len(entities), counts["constraint"],
            counts["sequence"], counts["hierarchy"], counts["series_mapping"],
            counts["region_rule"], counts[None],
        )

    result = (constraint_rows, sequence_rows, hierarchy_rows, series_mapping_rows, region_rule_rows)
    logger.info(
        "cpq_perf: _load_all_tables MISS (fresh scan) took %.3fs ws=%s prefix=%r "
        "constraint=%d sequence=%d hierarchy=%d series_mapping=%d region_rule=%d",
        time.monotonic() - _t0, workspace_id, catalog_prefix,
        len(constraint_rows), len(sequence_rows), len(hierarchy_rows),
        len(series_mapping_rows), len(region_rule_rows),
    )
    if cache is not None:
        cache[(workspace_id, catalog_prefix)] = result
    _TABLES_CACHE[_mod_key] = (time.monotonic(), result)
    return result


def _row_conditions_match(
    row: dict[str, Any], filled: dict[str, str], condition_pairs: list[tuple[str, str]],
) -> bool:
    """True if every populated condition attr/val pair on this row (attr2/
    val2 onward -- attr1/val1 is the target attribute/value, not a
    condition) is satisfied by the currently-filled attribute values --
    mirrors the AND-filter semantics of util.getConstraintVals's own
    filterCriteria matching (docs proof §4)."""
    for attr_col, val_col in condition_pairs[1:]:  # skip attr1/val1 (the target)
        condition_attr = str(row.get(attr_col) or "").strip()
        if not condition_attr:
            continue
        condition_val = row.get(val_col)
        if filled.get(condition_attr) != condition_val:
            return False
    return True


def resolve_whitelist_values(
    cpq_model: str, base_model: str, attr_var_name: str, filled: dict[str, str],
    workspace_id: int, catalog_prefix: str = "",
    cache: dict[tuple[int, str], tuple] | None = None,
) -> list[str] | None:
    """Legal values for `attr_var_name` given `cpq_model`/`base_model`, from
    every ingested constraint-shaped Data Table in this workspace (any
    ingested entity type whose rows match the CPQModel/BaseModel/attrN/valN
    signature, regardless of its ontology_type name or how many attrN/valN
    pairs it has).

    Returns:
      None -- no ingested constraint table has any row at all for this
        (cpq_model, base_model, attr_var_name) combination; genuinely
        unknown, not zero options.
      [] (empty list) -- rows exist for this attribute here, but none of
        their condition columns match the current `filled` values; a real,
        confirmed "no legal value under this context" answer.
      [v1, v2, ...] -- the real, catalog-sourced legal values, merged across
        every constraint-shaped table ingested into this workspace.
    """
    constraint_rows, _, _, _, _ = _load_all_tables(workspace_id, catalog_prefix, cache)
    any_row_matched = False
    legal: set[str] = set()

    for row in constraint_rows:
        keys = set(row.keys())
        condition_pairs = _attr_val_col_pairs(keys)
        if not condition_pairs:
            continue
        if row.get("CPQModel") != cpq_model:
            continue
        if row.get("BaseModel") not in (base_model, "ALL"):
            continue
        if row.get("attr1") != attr_var_name:
            continue
        any_row_matched = True
        if _row_conditions_match(row, filled, condition_pairs):
            legal.add(row["val1"])

    if not any_row_matched:
        return None
    return sorted(legal)


def governed_attr_names_for_base_model(
    cpq_model: str, base_model: str, workspace_id: int, catalog_prefix: str = "",
    cache: dict[tuple[int, str], tuple] | None = None,
) -> set[str] | None:
    """Every AttrName any ingested sequence-shaped Data Table lists for
    this exact (cpq_model, base_model) pair -- the set-valued sibling of
    `attribute_applies()`, computed ONCE per (cpq_model, base_model)
    instead of once per (cpq_model, base_model, attr_var_name).

    Confirmed live (2026-08-08): engine.CpqEngine._suppress_ungoverned_
    attrs previously called `attribute_applies()` once per candidate
    attribute (392 in one real catalog) times once per real CPQModel
    candidate for the base model, each call independently re-filtering
    the SAME up-to-47K-row sequence table from scratch. Once base model
    resolution started actually working (a separate fix), this became a
    genuine O(attrs x candidates x rows) cost on every evaluation pass --
    this precomputes the filtered scope once; callers do an O(1) set
    membership check per attribute instead.

    Returns None when no sequence table has ANY row at all for this
    (cpq_model, base_model) -- distinct from a confirmed empty set.
    """
    _, sequence_rows, _, _, _ = _load_all_tables(workspace_id, catalog_prefix, cache)
    scoped = [
        row for row in sequence_rows
        if row.get("CPQModel") == cpq_model
        and row.get("BaseModel") in (base_model, "ALL")
    ]
    if not scoped:
        return None
    return {row.get("AttrName") for row in scoped if row.get("AttrName")}


def attr_ever_governed_for_cpq_model(
    cpq_model: str, attr_var_name: str,
    workspace_id: int, catalog_prefix: str = "",
    cache: dict[tuple[int, str], tuple] | None = None,
) -> bool:
    """True if ANY sequence-shaped Data Table row for this CPQModel -- at
    ANY base model, not just the one currently active -- ever mentions
    `attr_var_name`. Distinguishes two very different reasons an attribute
    can be absent from `governed_attr_names_for_base_model`'s per-base-model
    set:

    1. The catalog tracks this attribute's applicability via sequence rows
       for OTHER base models of this same CPQModel, just not this one --
       a confident "not part of THIS base model" (e.g. wirelessCarrier_
       astro vs carrierSelectionMultiSelect_astro's mutual exclusivity).
    2. The catalog never tracks this attribute via sequence rows for this
       CPQModel at ANY base model at all -- confirmed live (2026-08-09):
       carrierSelectionMultiSelect_astro has real sequence coverage for
       exactly one (CPQModel, BaseModel) pair in the whole ingested
       catalog; every OTHER CPQModel candidate has none, so per-base-model
       absence there is silence, not a confident exclusion.

    Callers should suppress (drop from view) only case 1 -- case 2 has no
    real signal either way and should fall through to "ask the user" with
    the attribute's own real catalog-defined options, matching this
    codebase's never-guess/never-silently-drop convention (docs/CPQ_
    CARRIER_WIRELESS_FREQBAND_DATA_GAP_PROOF_2026_08_07.md §9's own
    "structurally valid but internally contradictory quote is worse than
    an honest ask" reasoning, extended from constraint-fill to visibility).

    Confirmed live (2026-08-09): the first version of this function did a
    fresh `any(... for row in sequence_rows)` scan (up to 46,865 rows) on
    EVERY call -- called once per non-governed attr, per candidate
    CPQModel, per evaluate_rules_loop pass -- reproducing the exact
    O(attrs x candidates x rows) cost `governed_attr_names_for_base_model`
    was already built to eliminate for the per-base-model case. With
    `_invalidate_inconsistent_paired_values` unable to converge for one
    real base model (H55TGT9RW8AN, `inconsistent` stuck at 2), this
    repeated across many passes and drove per-pass cost to 80-325s.
    Precomputes the full per-CPQModel AttrName set ONCE (memoized in
    `cache`, the same per-turn dict every other Data Table lookup here
    already shares), then does an O(1) set-membership check per call --
    same fix shape as `governed_attr_names_for_base_model` itself.
    """
    key = ("_ever_governed_attrs", workspace_id, catalog_prefix, cpq_model)
    if cache is not None and key in cache:
        ever_governed_attrs = cache[key]
    else:
        _, sequence_rows, _, _, _ = _load_all_tables(workspace_id, catalog_prefix, cache)
        ever_governed_attrs = {
            row.get("AttrName") for row in sequence_rows
            if row.get("CPQModel") == cpq_model and row.get("AttrName")
        }
        if cache is not None:
            cache[key] = ever_governed_attrs
    return attr_var_name in ever_governed_attrs


def attribute_applies(
    cpq_model: str, base_model: str, attr_var_name: str,
    workspace_id: int, catalog_prefix: str = "",
    cache: dict[tuple[int, str], tuple] | None = None,
) -> bool | None:
    """Whether `attr_var_name` is governed by this base model at all, per
    every ingested sequence-shaped Data Table in this workspace. Resolves
    the sibling question (e.g. wirelessCarrier_astro vs
    carrierSelectionMultiSelect_astro) with real, catalog-wide data instead
    of one live-session snapshot.

    Returns None when no sequence table has any data at all for this
    (cpq_model, base_model) -- distinct from a confirmed False. A thin
    per-attribute wrapper over `governed_attr_names_for_base_model` --
    callers checking MANY attributes for the same (cpq_model, base_model)
    should call that directly instead, once, rather than this in a loop
    (see its own docstring for the live-measured cost of doing otherwise).
    """
    scoped_names = governed_attr_names_for_base_model(
        cpq_model, base_model, workspace_id, catalog_prefix, cache,
    )
    if scoped_names is None:
        return None
    return attr_var_name in scoped_names


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


def resolve_invalid_product_variant(
    item_text: str, item_value: str, filled: dict[str, str],
    workspace_id: int, catalog_prefix: str = "",
    cache: dict[tuple[int, str], tuple] | None = None,
) -> str | None:
    """The real childCPQModel this product option maps to under the CURRENT
    `filled` context, from every ingested series-mapping-shaped Data Table
    (e.g. Seriesmodelsmapping.csv) in this workspace -- ONLY when it differs
    from `item_value` (i.e. this option isn't actually the real/orderable
    model here). Returns None when no row's childCPQModelLabel matches this
    option's own `item_text` at all, or none of a matching row's own
    attrN/opN/valN condition triples are ALL satisfied by `filled` (every
    triple with an unsupported op, i.e. anything but "=", never counts as
    satisfied -- never guess), or the matching row's childCPQModel already
    equals `item_value` (genuinely valid here, nothing to hide).

    Confirmed live (2026-08-08): Seriesmodelsmapping's row for
    (modelSelectionRegion_astro="NA", ultimateDestinationCountry="US") maps
    "APX NEXT™ International (Federal)" to childCPQModel "APX NEXT INTL
    FED_future" -- not the live "APX NEXT INTL FED" every other region's row
    for this same product maps to. That's Oracle CPQ's own data saying this
    variant isn't real yet for the US market — the option should not be
    offered. The rule meant to enforce this in the static export
    (util.getConstraintVals against hiddenConstraintMasterString_astro)
    can't, because that master-string attribute is always empty (docs/
    CPQ_CARRIER_WIRELESS_FREQBAND_DATA_GAP_PROOF_2026_08_07.md §7-§10) --
    this is a second, independent real Data Table with the true answer.
    """
    _, _, _, series_rows, _ = _load_all_tables(workspace_id, catalog_prefix, cache)
    norm_text = _normalize_label(item_text)
    for row in series_rows:
        label = row.get("childCPQModelLabel")
        if label is None or _normalize_label(str(label)) != norm_text:
            continue
        triples = _attr_op_val_triples(set(row.keys()))
        if not triples:
            continue
        all_satisfied = True
        for attr_col, op_col, val_col in triples:
            if str(row.get(op_col) or "").strip() != "=":
                all_satisfied = False
                break
            condition_attr = str(row.get(attr_col) or "").strip()
            if not condition_attr or filled.get(condition_attr) != row.get(val_col):
                all_satisfied = False
                break
        if not all_satisfied:
            continue
        child = row.get("childCPQModel")
        if not child:
            continue
        if child == item_value:
            return None
        return child
    return None


# Real ingested rows can carry stale/legacy CPQModel codes never purged from
# the source Oracle CPQ export -- confirmed live (2026-08-08): rows tagged
# "...-btaDelete-<timestamp>-<n>" (deleted-but-never-purged), "..._PO-<n>"
# (one-off, order-specific snapshots), "...-DEL", and "...-remove" all sit
# alongside the real, current catalog codes for the exact same BaseModel/
# attribute. Never treat these as real candidates -- they'd reintroduce
# exactly the kind of conflicting/dead data this module exists to filter
# out, AND (confirmed live) needlessly multiply the cost of every
# candidate-scoped lookup that iterates over discovered CPQModel codes.
_STALE_CPQ_MODEL_MARKERS: tuple[str, ...] = ("btadelete", "_po-")

# Checked as SUFFIXES, not substrings -- "-del"/"-remove" are short enough
# that a substring check risks a false positive on a real code that just
# happens to contain them (e.g. a hypothetical "...-DELTA" variant). Both
# confirmed live only ever appear as a trailing marker.
_STALE_CPQ_MODEL_SUFFIXES: tuple[str, ...] = ("-del", "-remove")


def _is_stale_cpq_model(cpq_model: str) -> bool:
    lowered = (cpq_model or "").lower()
    return (
        any(marker in lowered for marker in _STALE_CPQ_MODEL_MARKERS)
        or any(lowered.endswith(suffix) for suffix in _STALE_CPQ_MODEL_SUFFIXES)
    )


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
    constraint_rows, _, _, _, _ = _load_all_tables(workspace_id, catalog_prefix, cache)
    scoped = [
        r for r in constraint_rows
        if r.get("CPQModel") == cpq_model and r.get("BaseModel") in (base_model, "ALL")
    ]
    linked_pairs: set[tuple[str, str]] = set()
    for row in scoped:
        a1, a2 = row.get("attr1"), row.get("attr2")
        if a1 and a2 and a1 in filled and a2 in filled:
            linked_pairs.add((a1, a2))

    invalid: set[str] = set()
    for attr_a, attr_b in linked_pairs:
        val_a, val_b = filled.get(attr_a), filled.get(attr_b)
        matches = any(
            (row.get("attr1") == attr_a and row.get("val1") == val_a
             and row.get("attr2") == attr_b and row.get("val2") == val_b)
            or (row.get("attr1") == attr_b and row.get("val1") == val_b
                and row.get("attr2") == attr_a and row.get("val2") == val_a)
            for row in scoped
        )
        if not matches:
            invalid.add(attr_a)
            invalid.add(attr_b)
    return invalid
