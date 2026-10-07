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


def model_rows_and_base_models(
    cpq_model: str, workspace_id: int, catalog_prefix: str = "", cache: dict[tuple, Any] | None = None,
) -> tuple[list[dict[str, Any]], set[str]]:
    """The constraint rows of `cpq_model` and its real base models (blank and "ALL" excluded)."""
    norm_model = (cpq_model or "").strip().upper()
    if not norm_model:
        return [], set()
    rows = _model_rows(norm_model, workspace_id, catalog_prefix, cache)
    return rows, _base_models(rows)


def row_attr_values(row: dict[str, Any]) -> list[tuple[str, str]]:
    """(attribute, UPPER-CASE value) for every attr/val slot of a constraint row that has both."""
    out: list[tuple[str, str]] = []
    for n in (1, *CONDITION_COLUMN_SLOTS):
        attr = str(row.get(f"attr{n}") or "").strip()
        value = str(row.get(f"val{n}") or "").strip().upper()
        if attr and value:
            out.append((attr, value))
    return out


def model_base_models(
    cpq_model: str, workspace_id: int, catalog_prefix: str = "", cache: dict[tuple, Any] | None = None,
) -> set[str]:
    """Base models the constraint rows list for `cpq_model` (diagnostics)."""
    norm_model = (cpq_model or "").strip().upper()
    return _base_models(_model_rows(norm_model, workspace_id, catalog_prefix, cache)) if norm_model else set()


def explain_known_attrs(
    cpq_model: str, known_attrs: dict[str, str], workspace_id: int, catalog_prefix: str = "",
    cache: dict[tuple, Any] | None = None, ignore_attrs: frozenset[str] | set[str] = frozenset(),
) -> list[dict[str, Any]]:
    """Replays `derive_base_model_from_known_attrs` and says what each known attribute did (diagnostics only).

    One entry per known attribute that some base model's rows mention, with `applied_order` (the derivation applies
    attributes one after another in `known_attrs` order, so the order matters), `base_models_with_rows` and
    `base_models_matching` over all of the model's base models, `matching_among_remaining` (the test the derivation
    really uses: a match among the base models still left; 0 means the attribute is ignored), `remaining_before` and
    `remaining_after`, and a sample of the non-blank values the rows hold (catalog data). Entries that matched nothing
    among the remaining base models come first, so a cap keeps the useful ones. The known value itself is never
    returned, so no customer text can reach a log."""
    norm_model = (cpq_model or "").strip().upper()
    if not norm_model:
        return []
    rows = _model_rows(norm_model, workspace_id, catalog_prefix, cache)
    base_models = _base_models(rows)
    remaining = set(base_models)
    out: list[dict[str, Any]] = []
    for order, (attr_name, value) in enumerate(known_attrs.items()):
        if not value or attr_name in ignore_attrs:
            continue
        norm_value = str(value).strip().upper()
        with_rows: set[str] = set()
        matching: set[str] = set()
        row_values: set[str] = set()
        for row in rows:
            base_model = str(row.get("BaseModel") or "").strip()
            if base_model not in base_models:
                continue
            for n in (1, *CONDITION_COLUMN_SLOTS):
                if row.get(f"attr{n}") == attr_name:
                    with_rows.add(base_model)
                    row_value = str(row.get(f"val{n}") or "").strip().upper()
                    if row_value:
                        row_values.add(row_value)
            if _row_mentions(row, attr_name, norm_value):
                matching.add(base_model)
        if not with_rows:
            continue
        before = len(remaining)
        matched = matching & remaining
        if matched:        # the derivation's own step: only an attribute that matches a remaining base model narrows
            remaining &= matched | (remaining - with_rows)
        out.append({"attr": attr_name, "applied_order": order, "base_models_with_rows": len(with_rows),
                    "base_models_matching": len(matching), "matching_among_remaining": len(matched),
                    "remaining_before": before, "remaining_after": len(remaining),
                    "row_value_count": len(row_values), "row_values_sample": sorted(row_values)[:6]})
    out.sort(key=lambda e: e["matching_among_remaining"] != 0)          # stable: ignored attributes first
    return out[:20]


def narrowed_base_models(
    model_rows: list[dict[str, Any]], known_attrs: dict[str, str],
    ignore_attrs: frozenset[str] | set[str] = frozenset(),
) -> set[str]:
    """The base models of `model_rows` that the known attr/value pairs leave, applied one after another in
    `known_attrs` order (the derivation's own narrowing, shared so nothing else can drift from it).

    A base model with NO rows at all for an attr is unrestricted for it, not illegal: it is only excluded when it has
    rows for that attr and none of them allow this value. An attribute narrows only when some remaining base model
    matches its value. `ignore_attrs` names attrs whose values are guesses and must not drive the narrowing."""
    candidates = _base_models(model_rows)
    if len(candidates) <= 1:
        return candidates
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
            return candidates
    return candidates


def derive_base_model_from_known_attrs(
    cpq_model: str, known_attrs: dict[str, str], workspace_id: int,
    catalog_prefix: str = "", cache: dict[tuple, Any] | None = None,
    ignore_attrs: frozenset[str] | set[str] = frozenset(),
) -> str | None:
    """The single BaseModel left after intersecting this model's real base
    models (blank/"ALL" excluded) with every known attr/value's Whitelist
    evidence (`narrowed_base_models`); None when ambiguous or no coverage.
    Never guesses. `ignore_attrs` names attrs whose values are guesses
    (blind-filled) and must not drive the derivation."""
    norm_model = (cpq_model or "").strip().upper()
    if not norm_model:
        return None
    remaining = narrowed_base_models(_model_rows(norm_model, workspace_id, catalog_prefix, cache),
                                     known_attrs, ignore_attrs)
    return next(iter(remaining)) if len(remaining) == 1 else None
