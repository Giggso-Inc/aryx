"""Implied legal values from Whitelist condition-column evidence.

Port of aryxent ``_scan_condition_column_values`` /
``infer_implied_legal_values`` (PR 7 + PR 15 base-model scoping) and the
``Basemodeltoconfig`` reader the family tier needs. Pure reads; callers gate
on ``cpq_infer_legal_values_enabled``.
"""
from __future__ import annotations

import logging
from typing import Any

from aryx.cpq.data_table.data_table_loader import (
    _SHAPE_SCAN_CACHES,
    _cached_shape_scan,
    _load_all_tables,
)

CONDITION_COLUMN_SLOTS = range(2, 9)  # attr2..attr8 / val2..val8

logger = logging.getLogger(__name__)

# Module-level TTL cache for the Basemodeltoconfig scan (cleared by
# data_table_loader._clear_tables_cache via the shared registry).
_BASEMODEL_CONFIG_CACHE: dict[tuple[int, str], tuple[float, list[dict[str, Any]]]] = {}
_BASEMODEL_CONFIG_CACHE_LAST_SEEN_MARKER: list[float | None] = [None]
_SHAPE_SCAN_CACHES.append(_BASEMODEL_CONFIG_CACHE)


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
    rows = _cached_shape_scan(
        _BASEMODEL_CONFIG_CACHE, _BASEMODEL_CONFIG_CACHE_LAST_SEEN_MARKER,
        workspace_id, catalog_prefix, _is_basemodel_to_config_shaped,
        "_load_basemodel_to_config_rows",
    )
    if cache is not None:
        cache[key] = rows
    return rows


def _contradicts_filled(row: dict[str, Any], attr_var_name: str, filled: dict[str, str]) -> bool:
    """True when another condition column of `row` names an attr that is
    already filled with a different value (case-insensitive)."""
    for slot in CONDITION_COLUMN_SLOTS:
        name = row.get(f"attr{slot}")
        if not name or name == attr_var_name or name not in filled:
            continue
        have = str(filled[name] or "").strip().lower()
        want = str(row.get(f"val{slot}") or "").strip().lower()
        if have and want and have != want:
            return True
    return False


def _scan_condition_column_values(
    rows: list[dict[str, Any]], attr_var_name: str, cpq_models: set[str],
    base_model: str = "", filled: dict[str, str] | None = None,
) -> set[str]:
    """Distinct values `attr_var_name` is paired with when it appears as a
    CONDITION (attr2..attr8) on constraint rows of `cpq_models` (already
    stripped/uppercased). `base_model` (optional) also requires
    ``BaseModel in (base_model, "ALL")`` (PR 15). `filled` (optional) drops
    rows whose OTHER condition columns contradict an already-filled attr
    (case-insensitive)."""
    found: set[str] = set()
    for row in rows:
        if str(row.get("CPQModel") or "").strip().upper() not in cpq_models:
            continue
        if base_model and row.get("BaseModel") not in (base_model, "ALL"):
            continue
        if filled and _contradicts_filled(row, attr_var_name, filled):
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
    filled: dict[str, str] | None = None, allow_wider_tiers: bool = False,
) -> tuple[list[str], str] | None:
    """Implied legal set when Whitelist has no direct attr1 declaration.

    Tiers: ``model_basemodel`` (cpq_model AND base_model), ``model``, then
    ``family`` (same productLine) only when both are empty. With a
    `base_model` the inference stays in the ``model_basemodel`` tier whenever
    that base model has rows for the attribute (the wider tiers pool values
    across sibling base models and could blind-fill a value only valid for
    another one); it falls through to the wider tiers only when the base
    model has NO rows at all for the attribute (sparse data), or always when
    `allow_wider_tiers=True`. `filled` additionally drops rows whose other
    conditions contradict already-filled attrs. Returns
    ``(sorted values, tier)`` or None -- never fabricates."""
    constraint_rows, _, _, _, _ = _load_all_tables(workspace_id, catalog_prefix, cache)
    norm_model = (cpq_model or "").strip().upper()
    if not norm_model:
        return None
    if base_model:
        scoped = _scan_condition_column_values(
            constraint_rows, attr_var_name, {norm_model}, base_model=base_model,
            filled=filled,
        )
        if scoped:
            return sorted(scoped), "model_basemodel"
        if not allow_wider_tiers:
            # Sparse vs conflicting: if this base model HAS rows for the attr
            # but their other conditions contradict `filled`, that is a real
            # conflict -> infer nothing. If it has no rows at all (sparse
            # data), fall through to the wider tiers instead of giving up.
            if _scan_condition_column_values(
                constraint_rows, attr_var_name, {norm_model}, base_model=base_model,
            ):
                return None
            # Sparse fallback: values may come from sibling base models. Logged
            # so any wrong blind-fill is visible during the flag rollout.
            logger.info(
                "cpq: inferred_legal_values sparse base-model fallback attr=%r "
                "cpq_model=%r base_model=%r -> wider tiers (sibling base models "
                "may contribute)", attr_var_name, norm_model, base_model,
            )
    model_values = _scan_condition_column_values(
        constraint_rows, attr_var_name, {norm_model}, filled=filled,
    )
    if model_values:
        return sorted(model_values), "model"
    family = _family_models(
        norm_model, _load_basemodel_to_config_rows(workspace_id, catalog_prefix, cache),
    )
    if not family:
        return None
    family_values = _scan_condition_column_values(
        constraint_rows, attr_var_name, family, filled=filled,
    )
    return (sorted(family_values), "family") if family_values else None
