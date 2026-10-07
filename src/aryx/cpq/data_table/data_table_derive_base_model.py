"""Narrow a CPQModel's base models to exactly one from already-known attrs.

Port of aryxent ``derive_base_model_from_known_attrs`` (PR 8). Callers gate
on ``cpq_derive_base_model_enabled``.
"""
from __future__ import annotations

from typing import Any

from aryx.cpq.data_table.data_table_inference import CONDITION_COLUMN_SLOTS
from aryx.cpq.data_table.data_table_loader import _load_all_tables


def _row_mentions(row: dict[str, Any], attr_name: str, norm_value: str) -> bool:
    """True when attr/value is the row's attr1/val1 target or any attr2..8
    condition (case-insensitive value)."""
    return any(
        row.get(f"attr{n}") == attr_name
        and str(row.get(f"val{n}") or "").strip().upper() == norm_value
        for n in (1, *CONDITION_COLUMN_SLOTS)
    )


def _model_rows(norm_model: str, workspace_id: int, catalog_prefix: str, cache: dict | None) -> list[dict[str, Any]]:
    constraint_rows, _, _, _, _ = _load_all_tables(workspace_id, catalog_prefix, cache)
    return [r for r in constraint_rows if str(r.get("CPQModel") or "").strip().upper() == norm_model]


def _base_models(model_rows: list[dict[str, Any]]) -> set[str]:
    """The model's real base models (blank and "ALL" excluded)."""
    return {
        bm for bm in (str(r.get("BaseModel") or "").strip() for r in model_rows)
        if bm and bm.upper() != "ALL"
    }


def model_base_models(
    cpq_model: str, workspace_id: int, catalog_prefix: str = "", cache: dict[tuple, Any] | None = None,
) -> set[str]:
    """Base models the constraint rows list for `cpq_model` (diagnostics)."""
    norm_model = (cpq_model or "").strip().upper()
    return _base_models(_model_rows(norm_model, workspace_id, catalog_prefix, cache)) if norm_model else set()


def derive_base_model_from_known_attrs(
    cpq_model: str, known_attrs: dict[str, str], workspace_id: int,
    catalog_prefix: str = "", cache: dict[tuple, Any] | None = None,
    ignore_attrs: frozenset[str] | set[str] = frozenset(),
) -> str | None:
    """The single BaseModel left after intersecting this model's real base
    models (blank/"ALL" excluded) with every known attr/value's Whitelist
    evidence; None when ambiguous or no coverage. Never guesses.

    A base model with NO rows at all for an attr is unrestricted for it, not
    illegal: it is only excluded when it has rows for that attr and none of
    them allow this value. `ignore_attrs` names attrs whose values are
    guesses (blind-filled) and must not drive the derivation."""
    norm_model = (cpq_model or "").strip().upper()
    if not norm_model:
        return None
    model_rows = _model_rows(norm_model, workspace_id, catalog_prefix, cache)
    candidates = _base_models(model_rows)
    if not candidates:
        return None
    if len(candidates) == 1:
        return next(iter(candidates))
    for attr_name, value in known_attrs.items():
        if not value or attr_name in ignore_attrs:
            continue
        norm_value = str(value).strip().upper()
        matched = {
            bm for r in model_rows
            if (bm := str(r.get("BaseModel") or "").strip()) in candidates
            and _row_mentions(r, attr_name, norm_value)
        }
        if matched:
            has_rows = {
                bm for r in model_rows
                if (bm := str(r.get("BaseModel") or "").strip()) in candidates
                and any(r.get(f"attr{n}") == attr_name for n in (1, *CONDITION_COLUMN_SLOTS))
            }
            candidates &= matched | (candidates - has_rows)
        if len(candidates) == 1:
            return next(iter(candidates))
    return None
