"""Dropping a removed multi-select option's own per-option quantity
attr, split out of `_handle_multi_select_removal` (Phase 4/11-phase
ask_api decomposition, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md)
purely to keep the sibling `ask_multi_select_removal_recompute.py` under
the line cap. Logic unchanged from the original inline block.
`_cpq_engine` is read through the ask_api MODULE object (not imported by
name) since at least one test replaces the whole singleton via
`patch("aryx.api.ask_api._cpq_engine")`.
"""

from __future__ import annotations

from typing import Any



def _drop_related_quantity_attrs(
    session: Any, attrs: list, changed_attr: Any, to_remove: list[str],
) -> list[str]:
    """Drops the removed option's own per-option quantity attr (via
    resolve_array_grid_links) — a quantity for a mount no longer selected
    is stale data, not a value worth keeping around or re-showing. Returns
    the display labels of whatever quantity attrs were actually dropped.
    """
    from aryx.api import ask_api as _ask_api_module
    _cpq_engine = _ask_api_module._cpq_engine
    grid_links = _cpq_engine.resolve_array_grid_links(attrs)
    qty_map = grid_links.get(changed_attr.variable_name, {})
    dropped_qty_labels: list[str] = []
    for removed_iv in to_remove:
        qty_vn = qty_map.get(removed_iv.strip().lower())
        if qty_vn and qty_vn in session.filled:
            qty_attr = next((a for a in attrs if a.variable_name == qty_vn), None)
            dropped_qty_labels.append(
                _cpq_engine.disambiguated_label(qty_attr, attrs) if qty_attr else qty_vn
            )
            session.filled.pop(qty_vn, None)
            session.display_filled.pop(qty_vn, None)
            session.filled_source.pop(qty_vn, None)
            session.pending_variables = [v for v in session.pending_variables if v != qty_vn]
    return dropped_qty_labels
