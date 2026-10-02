"""Data-Table-driven conflict/inconsistency resolution helpers -- part of
the Data-Table-conflict helper cluster extracted from ``cpq/engine.py``
(Phase 4 step 1, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Stateless,
purely-functional wrappers over already-external ``data_table_resolver``
calls.
"""

from __future__ import annotations

from typing import Any

from aryx.cpq.catalog_profile import resolve_base_model_vn
from aryx.raven_log import raven_log, would_log
from aryx.cpq.data_table_bridge.candidates import _cpq_model_candidates
from aryx.cpq.data_table.data_table_resolver import (
    find_inconsistent_filled_pairs as dt_find_inconsistent_filled_pairs,
    find_inconsistent_filled_pairs_detailed as dt_find_inconsistent_filled_pairs_detailed,
    resolve_whitelist_values as dt_resolve_whitelist_values,
)
from aryx.cpq.state import MenuOption

# Same three "customer already confirmed this" source tags CpqEngine itself
# defines as `_CONFIRMED_SOURCES` -- duplicated here (not imported) to avoid
# a circular import, since `engine.py` imports THIS package, not the
# reverse. Keep in sync with `CpqEngine._CONFIRMED_SOURCES` in engine.py.
_CONFIRMED_SOURCES: frozenset[str] = frozenset({"user", "hint", "cascade"})


def _invalidate_inconsistent_paired_values(
    filled: dict[str, str], sources: dict[str, str],
    workspace_id: int | None, catalog_prefix: str = "",
    cache: dict[tuple[int, str], tuple] | None = None,
) -> set[str]:
    """Variable names to clear because their currently-filled value
    contradicts a linked attribute's currently-filled value, per real
    ingested Data Table rows. Never clears a variable whose value traces
    back to something the customer said or confirmed (`_CONFIRMED_SOURCES`).
    `None`/no workspace_id is a complete no-op.
    """
    if workspace_id is None:
        return set()
    base_model = filled.get(resolve_base_model_vn(filled, workspace_id, catalog_prefix, cache), "")
    if not base_model:
        return set()
    product = filled.get("productSelectionProduct_all", "")
    cands = _cpq_model_candidates(
        product, workspace_id, catalog_prefix, cache, base_model=base_model,
    )
    # Intersection, not union: `base_model` can legitimately map to multiple
    # real CPQModel candidates. A combo is only a real contradiction if NO
    # candidate model accepts it.
    per_model_invalid = [
        dt_find_inconsistent_filled_pairs(
            cpq_model, base_model, filled, workspace_id, catalog_prefix, cache,
        )
        for cpq_model in cands
    ]
    invalid = set.intersection(*per_model_invalid) if per_model_invalid else set()
    return {vn for vn in invalid if sources.get(vn) not in _CONFIRMED_SOURCES}


def find_confirmed_data_table_conflicts(
    filled: dict[str, str], sources: dict[str, str],
    workspace_id: int | None, catalog_prefix: str = "",
    cache: dict[tuple[int, str], tuple] | None = None,
) -> set[tuple[str, str]]:
    """The specific edge case `_invalidate_inconsistent_paired_values`
    deliberately leaves untouched: a real, data-proven-invalid pair where
    BOTH sides are customer-confirmed. Neither side can be silently
    self-corrected, so this is surfaced for an explicit re-ask instead.
    `None`/no workspace_id, or no base model resolved yet, is a complete
    no-op.
    """
    if workspace_id is None:
        return set()
    base_model = filled.get(resolve_base_model_vn(filled, workspace_id, catalog_prefix, cache), "")
    if not base_model:
        return set()
    product = filled.get("productSelectionProduct_all", "")
    cands = _cpq_model_candidates(
        product, workspace_id, catalog_prefix, cache, base_model=base_model,
    )
    confirmed_conflicts: set[tuple[str, str]] = set()
    for cpq_model in cands:
        for attr_a, attr_b in dt_find_inconsistent_filled_pairs_detailed(
            cpq_model, base_model, filled, workspace_id, catalog_prefix, cache,
        ):
            if (sources.get(attr_a) in _CONFIRMED_SOURCES
                    and sources.get(attr_b) in _CONFIRMED_SOURCES):
                confirmed_conflicts.add((attr_a, attr_b))
    return confirmed_conflicts


def _log_lookup(fn: str, vn: str, outcome: str, reason: str, *, models: list | None = None,
                candidate_count: int = 0, legal: Any = "n/a", falls_to: str | None = None,
                discarded: bool = False) -> None:
    """G4 -- ask.datatable.lookup (DEBUG, always) plus WARN P3 when several values were dropped
    and the pick falls to raw catalog order. ``legal`` is the three-state legal set."""
    state = "unknown_none" if legal is None else ("n/a" if legal == "n/a" else ("empty" if legal == [] else "list"))
    ctxd = {
        "selected_option": outcome, "available_options": ["single_match", "ambiguous_discarded", "none"],
        "reason_code": reason, "policy_version": "data_table_bridge_v1", "object_id": vn, "trigger": fn,
        "cpq_models": models or [], "candidate_count": candidate_count, "outcome": outcome,
        "legal_set_state": state, "legal_set_size": len(legal) if isinstance(legal, list) else None,
        "falls_to": falls_to}
    if discarded:
        raven_log("WARN", "P3", "ask.datatable.discarded several legal values dropped, pick falls to raw catalog order",
                  error_code="ARYX_ASK_DATATABLE_DISCARDED", context=ctxd)
    if would_log("DEBUG"):
        raven_log("DEBUG", "P4", "ask.datatable.lookup result", context=ctxd)


def _resolve_via_data_tables(
    vn: str, filled: dict[str, str], valid_opts: list[MenuOption],
    workspace_id: int | None, catalog_prefix: str = "",
    cache: dict[tuple[int, str], tuple] | None = None,
) -> MenuOption | None:
    """Real ingested Oracle CPQ Data Table lookup, tried only when
    script-based governance already failed to resolve `vn`. Returns a menu
    option ONLY when the table resolves to exactly one legal value that is
    also a real option on this attr -- 2+ legal values, 0 legal values, no
    table data at all, or no `workspace_id` all return None (never guess).
    """
    if workspace_id is None:
        _log_lookup("_resolve_via_data_tables", vn, "none", "NO_WORKSPACE_ID")
        return None
    base_model = filled.get(resolve_base_model_vn(filled, workspace_id, catalog_prefix, cache), "")
    if not base_model:
        _log_lookup("_resolve_via_data_tables", vn, "none", "NO_BASE_MODEL_YET")
        return None
    product = filled.get("productSelectionProduct_all", "")
    _models = list(_cpq_model_candidates(
        product, workspace_id, catalog_prefix, cache, base_model=base_model,
    ))
    _ambiguous = 0
    _widest = 0
    for cpq_model in _models:
        values = dt_resolve_whitelist_values(
            cpq_model, base_model, vn, filled, workspace_id, catalog_prefix, cache,
        )
        if values is None:
            continue
        if len(values) != 1:
            # This candidate is ambiguous -- try the REST of the candidate
            # tuple before giving up (same "continue past ambiguous, don't
            # abort" contract `_resolve_narrowed_legal_values` uses below).
            _ambiguous += 1
            _widest = max(_widest, len(values))
            continue
        _hit = next((o for o in valid_opts if o.item_value == values[0]), None)
        _log_lookup("_resolve_via_data_tables", vn, "single_match", "SINGLE_LEGAL_VALUE", models=_models,
                    candidate_count=len(values), legal=list(values),
                    falls_to=None if _hit is not None else "value_not_in_valid_opts")
        return _hit
    if _ambiguous:
        _log_lookup("_resolve_via_data_tables", vn, "ambiguous_discarded", "AMBIGUOUS_DISCARDED", models=_models,
                    candidate_count=_widest, legal="n/a", falls_to="raw_catalog_order", discarded=True)
    else:
        _log_lookup("_resolve_via_data_tables", vn, "none", "NO_TABLE_ROWS", models=_models)
    return None


def _resolve_narrowed_legal_values(
    vn: str, filled: dict[str, str], workspace_id: int, catalog_prefix: str = "",
    cache: dict[tuple[int, str], tuple] | None = None,
) -> list[str] | None:
    """Real ingested Data Table whitelist for `vn`, however many values it
    narrows to -- unlike `_resolve_via_data_tables` (which only ever
    returns when exactly one value is confidently correct), this returns
    the full narrowed set. `None` -- no ingested table has any row for
    this attr in this context; `[]` -- real rows exist but none match the
    current filled state; `[v1, v2, ...]` -- the real, catalog-sourced
    legal set, however many members.
    """
    base_model = filled.get(resolve_base_model_vn(filled, workspace_id, catalog_prefix, cache), "")
    if not base_model:
        _log_lookup("_resolve_narrowed_legal_values", vn, "none", "NO_BASE_MODEL_YET", legal=None)
        return None
    product = filled.get("productSelectionProduct_all", "")
    _models = list(_cpq_model_candidates(
        product, workspace_id, catalog_prefix, cache, base_model=base_model,
    ))
    for cpq_model in _models:
        values = dt_resolve_whitelist_values(
            cpq_model, base_model, vn, filled, workspace_id, catalog_prefix, cache,
        )
        if values is not None:
            _log_lookup("_resolve_narrowed_legal_values", vn, "single_match" if len(values) == 1 else (
                "none" if not values else "ambiguous_discarded"),
                "LEGAL_SET_FOUND" if values else "LEGAL_SET_EMPTY", models=_models,
                candidate_count=len(values), legal=list(values))
            return values
    _log_lookup("_resolve_narrowed_legal_values", vn, "none", "NO_TABLE_ROWS", models=_models, legal=None)
    return None
