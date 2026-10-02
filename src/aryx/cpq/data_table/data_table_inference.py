"""Implied legal values from Whitelist condition-column evidence.

Port of aryxent ``_scan_condition_column_values`` /
``infer_implied_legal_values`` (PR 7 + PR 15 base-model scoping) and the
``Basemodeltoconfig`` reader the family tier needs. Pure reads; callers gate
on ``cpq_infer_legal_values_enabled``.
"""
from __future__ import annotations

from typing import Any

from aryx.cpq.data_table.data_table_loader import _load_all_tables
from aryx.cpq.rdb.rdb import get_cpq_rdb

CONDITION_COLUMN_SLOTS = range(2, 9)  # attr2..attr8 / val2..val8


def _is_basemodel_to_config_shaped(keys: set[str]) -> bool:
    return {"displayModel", "cpqModel", "baseModel"} <= keys


def _load_basemodel_to_config_rows(
    workspace_id: int, catalog_prefix: str = "",
    cache: dict[tuple, Any] | None = None,
) -> list[dict[str, Any]]:
    """Standalone scan for Basemodeltoconfig-shaped rows (kept out of
    _load_all_tables' fixed 5-tuple); memoized in the per-turn cache."""
    key = (workspace_id, catalog_prefix, "basemodel_to_config")
    if cache is not None and key in cache:
        return cache[key]
    rows: list[dict[str, Any]] = []
    for entities in get_cpq_rdb().fetch_all_entities_grouped_by_type(workspace_id).values():
        for _eid, attrs in entities:
            if _is_basemodel_to_config_shaped(set(attrs.keys())):
                rows.append(attrs)
    if cache is not None:
        cache[key] = rows
    return rows


def _scan_condition_column_values(
    rows: list[dict[str, Any]], attr_var_name: str, cpq_models: set[str],
    base_model: str = "",
) -> set[str]:
    """Distinct values `attr_var_name` is paired with when it appears as a
    CONDITION (attr2..attr8) on constraint rows of `cpq_models` (already
    stripped/uppercased). `base_model` (optional) also requires
    ``BaseModel in (base_model, "ALL")`` (PR 15)."""
    found: set[str] = set()
    for row in rows:
        if str(row.get("CPQModel") or "").strip().upper() not in cpq_models:
            continue
        if base_model and row.get("BaseModel") not in (base_model, "ALL"):
            continue
        for slot in CONDITION_COLUMN_SLOTS:
            if row.get(f"attr{slot}") != attr_var_name:
                continue
            val = row.get(f"val{slot}")
            if val:
                found.add(val)
    return found


def _family_models(norm_model: str, family_rows: list[dict[str, Any]]) -> set[str]:
    """Sibling CPQModels sharing `norm_model`'s Basemodeltoconfig productLine."""
    product_line = next(
        (
            str(r.get("productLine") or "").strip() for r in family_rows
            if str(r.get("cpqModel") or "").strip().upper() == norm_model and r.get("productLine")
        ),
        "",
    )
    if not product_line:
        return set()
    models = {
        str(r.get("cpqModel") or "").strip().upper() for r in family_rows
        if str(r.get("productLine") or "").strip() == product_line
    }
    models.discard("")
    return models


def infer_implied_legal_values(
    attr_var_name: str, cpq_model: str, workspace_id: int, catalog_prefix: str = "",
    cache: dict[tuple, Any] | None = None, base_model: str = "",
) -> tuple[list[str], str] | None:
    """Implied legal set when Whitelist has no direct attr1 declaration.

    Tiers: ``model_basemodel`` (cpq_model AND base_model), ``model``, then
    ``family`` (same productLine) only when both are empty. Returns
    ``(sorted values, tier)`` or None -- never fabricates."""
    constraint_rows, _, _, _, _ = _load_all_tables(workspace_id, catalog_prefix, cache)
    norm_model = (cpq_model or "").strip().upper()
    if not norm_model:
        return None
    if base_model:
        scoped = _scan_condition_column_values(
            constraint_rows, attr_var_name, {norm_model}, base_model=base_model,
        )
        if scoped:
            return sorted(scoped), "model_basemodel"
    model_values = _scan_condition_column_values(constraint_rows, attr_var_name, {norm_model})
    if model_values:
        return sorted(model_values), "model"
    family = _family_models(
        norm_model, _load_basemodel_to_config_rows(workspace_id, catalog_prefix, cache),
    )
    if not family:
        return None
    family_values = _scan_condition_column_values(constraint_rows, attr_var_name, family)
    return (sorted(family_values), "family") if family_values else None
