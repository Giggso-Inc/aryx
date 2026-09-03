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

Rows are classified by TABLE SHAPE (see `cpq.data_table_shapes` for the
four shapes and how a new one gets added) before this module's own
resolver functions below operate on them.
"""
from __future__ import annotations

from typing import Any

from aryx.cpq.data_table_loader import (
    _clear_tables_cache,
    _load_all_tables,
    _TABLES_CACHE_TTL_SECONDS,
)
from aryx.cpq.data_table_shapes import (
    _attr_op_val_triples,
    _attr_val_col_pairs,
    _normalize_label,
)
from aryx.cpq.rdb import get_cpq_rdb

# _load_all_tables, _clear_tables_cache, and the module-level table cache
# moved to cpq/data_table_loader.py (Raven Style Compliance Plan, Phase 2a,
# 2026-09-03) -- re-imported above so every existing caller of this module
# (doc_discovery.py's deferred import, this file's own resolver functions
# below, and the test suite's direct attribute access/patching) keeps
# working unchanged. `get_cpq_rdb` is NOT re-exported for that purpose --
# tests that fake the RDB for a call path going through _load_all_tables
# must patch `aryx.cpq.data_table_loader.get_cpq_rdb` now, since that's the
# module whose own namespace _load_all_tables's internal call resolves
# against.


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


def governed_required_attr_names_for_base_model(
    cpq_model: str, base_model: str, workspace_id: int, catalog_prefix: str = "",
    cache: dict[tuple[int, str], tuple] | None = None,
) -> set[str] | None:
    """The Required-only sibling of `governed_attr_names_for_base_model` --
    every AttrName an ingested sequence-shaped Data Table (AttrSequence)
    lists for this exact (cpq_model, base_model) pair with
    optionOrReqFlag == "R" (docs/CPQ_Beautify_Mandatory_Section_
    Miscategorization_2026_08_19.md).

    "R" alone means "must end up with SOME value" -- it does NOT mean
    "genuinely asked to the customer as Mandatory User Input". Many R-
    flagged attrs are auto-resolved by a Whitelist/Defaultinattr row
    (both pooled into the same constraint-shaped `_load_all_tables`
    bucket) rather than ever being a live decision -- callers using this
    for a "Mandatory User Input" classification MUST additionally check
    `resolve_whitelist_values(...) is None` per candidate attribute (i.e.
    no constraint-shaped row resolves it) before treating it as a genuine
    customer-facing Mandatory field. This function only answers the R/O
    question; it does not attempt the second, data-table-coverage check.

    Returns None under the same "no sequence coverage at all for this
    (cpq_model, base_model)" condition `governed_attr_names_for_base_model`
    uses -- distinct from a confirmed empty set.
    """
    _, sequence_rows, _, _, _ = _load_all_tables(workspace_id, catalog_prefix, cache)
    scoped = [
        row for row in sequence_rows
        if row.get("CPQModel") == cpq_model
        and row.get("BaseModel") in (base_model, "ALL")
    ]
    if not scoped:
        return None
    return {
        row.get("AttrName") for row in scoped
        if row.get("AttrName") and row.get("optionOrReqFlag") == "R"
    }


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
