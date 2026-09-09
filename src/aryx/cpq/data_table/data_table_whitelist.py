"""Resolves legal values for an attribute from ingested constraint-shaped
Data Table rows, matching util.getConstraintVals's own filterCriteria AND
semantics.

Split out of `cpq/data_table_resolver.py` (Raven Style Compliance Plan,
Phase 2a, 2026-09-03).
"""
from __future__ import annotations

from typing import Any

from aryx.cpq.data_table.data_table_loader import _load_all_tables
from aryx.cpq.data_table.data_table_shapes import _attr_val_col_pairs


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
