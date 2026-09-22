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


def _constraint_index_by_cpq_model_and_attr(
    workspace_id: int, catalog_prefix: str, cache: dict[tuple, Any] | None,
) -> dict[tuple[str, str], list[tuple[dict[str, Any], list[tuple[str, str]]]]]:
    """Precomputed once per (workspace_id, catalog_prefix): every constraint-
    shaped row, keyed by (CPQModel, attr1), paired with its own already-
    computed attrN/valN condition_pairs -- so resolve_whitelist_values no
    longer rescans every ingested constraint row on every call.

    BaseModel is intentionally NOT part of the index key: a row's BaseModel
    can be "ALL" (matches every base model), so indexing on it would still
    require checking each candidate against both its own BaseModel and
    "ALL". (CPQModel, attr1) alone already narrows the scan from every
    ingested constraint row down to just the handful naming this one
    attribute for this one CPQModel; the caller applies the BaseModel
    match and _row_conditions_match against that already-narrow list.

    Confirmed live (2026-09-17, workspace 97): resolve_whitelist_values
    previously rescanned every constraint row on every call -- once per
    unresolved attribute per auto_fill pass, for up to 8 evaluate_rules_
    loop passes, against the same handful of non-converging attributes
    every pass -- an O(attrs x passes x rows) cost confirmed via a live
    py-spy dump (active+gil inside resolve_whitelist_values for
    110-266s/pass). Same shape attr_ever_governed_for_cpq_model was fixed
    for on 2026-08-09; this memoizes the same way, sharing the per-turn
    `cache` dict every other Data Table lookup here already uses, keyed
    distinctly from _load_all_tables's own (workspace_id, catalog_prefix)
    tuple key.
    """
    key = ("_constraint_index", workspace_id, catalog_prefix)
    if cache is not None and key in cache:
        return cache[key]

    constraint_rows, _, _, _, _ = _load_all_tables(workspace_id, catalog_prefix, cache)
    index: dict[tuple[str, str], list[tuple[dict[str, Any], list[tuple[str, str]]]]] = {}
    for row in constraint_rows:
        condition_pairs = _attr_val_col_pairs(set(row.keys()))
        if not condition_pairs:
            continue
        row_cpq_model = row.get("CPQModel")
        row_attr_var_name = row.get("attr1")
        if not row_cpq_model or not row_attr_var_name:
            continue
        index.setdefault((row_cpq_model, row_attr_var_name), []).append((row, condition_pairs))

    if cache is not None:
        cache[key] = index
    return index


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

    Looks up candidates via _constraint_index_by_cpq_model_and_attr instead
    of rescanning every constraint row -- see that function's docstring for
    why this was necessary (a real, live, confirmed 110-266s/pass incident).
    """
    candidates = _constraint_index_by_cpq_model_and_attr(
        workspace_id, catalog_prefix, cache,
    ).get((cpq_model, attr_var_name), [])
    any_row_matched = False
    legal: set[str] = set()

    for row, condition_pairs in candidates:
        if row.get("BaseModel") not in (base_model, "ALL"):
            continue
        any_row_matched = True
        if _row_conditions_match(row, filled, condition_pairs):
            legal.add(row["val1"])

    if not any_row_matched:
        return None
    return sorted(legal)
