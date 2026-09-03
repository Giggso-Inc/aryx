"""Classifies an ingested Data Table row by the KEYS its JSONB attributes
actually have, not by its ontology_type name or the table's filename.

Every real Data Table export seen so far is one of four column signatures:

  "constraint"-shaped  -- CPQModel, BaseModel, attr1/val1 [, attr2/val2 ...]
                          (the source of hiddenConstraintMasterString_astro).
                          Column COUNT for the attrN/valN pairs varies by
                          export -- detected from the ingested attributes'
                          own keys, not hardcoded.
  "sequence"-shaped     -- CPQModel, BaseModel, AttrName, Seq[, optionOrReqFlag]
                          (the source of hiddenMasterStringForAstroPortable_astro).
  "hierarchy"-shaped    -- Product, cpqModelName[, productFamily, productLine,
                          ...] (the source of the Product -> CPQModel-family
                          mapping, e.g. CPQModelHierarchy.csv). Maps a product
                          name to its coarse product-FAMILY code only (e.g.
                          "APX NEXT ENHANCED" -> "APXNEXT", not
                          "APXNEXTENHANCED") -- used only as a fallback for
                          products with no constraint-row coverage in
                          `data_table_resolver.resolve_product_cpq_models_from_rows`,
                          never to override it.
  "region_rule"-shaped  -- model, value, region, ruleType, attribute[, UDCC]
                          (e.g. NewCountryRegMapping.csv) -- per-(CPQModel,
                          region[, country]) ALLOW/DISALLOW rows for a named
                          attribute. Confirmed live (2026-08-10): a real,
                          non-hardcoded resolution path for attributes Oracle
                          CPQ's own script-based recommendation rules
                          otherwise compute at runtime against a live table
                          this repo never has ingested (e.g. Base Model's
                          "Set Base Model" rules query `Oracle_BomItemMap`,
                          absent from every export seen so far).

A new rule referencing a never-seen-before table needs zero new code here IF
its ingested rows match one of these shapes -- only a genuinely new column
signature needs a new detector, added to `_SHAPE_DETECTORS` below.

Split out of `cpq/data_table_resolver.py` (Raven Style Compliance Plan,
Phase 2a, 2026-09-03).
"""
from __future__ import annotations


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
