"""STEP 5 explicit decline of an optional multi-select, split out of
`_run_cpq_turn_inner` (Phase 10/11-phase ask_api decomposition,
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). An empty selection IS
the answer: record it as user-confirmed so auto_fill never re-resolves
or re-asks it. A grid-selector attr can stay pending across turns so the
customer can add several rows (docs/CPQ_SVX_MOUNTING_TYPE_ARRAY_GRID_
MULTI_SELECT_PLAN_2026_08_25.md) — a decline reached AFTER 1+ real picks
means "no more rows", not "erase what I already picked"; only wipe to
[] the first time (no picks yet). Preserved picks are revalidated
against the SAME freshly-recomputed `pending_constrained` this turn's
answer just checked itself against (Raven review, PR #277). Logic
unchanged from the original inline block. `_cpq_engine` and `logger` are
read through the ask_api module object (not imported by name) since
tests patch several ask_api names by dotted path.
"""

from __future__ import annotations

from typing import Any

from aryx.api import ask_api as _ask_api_module


def _step9_decline_optional_multiselect(
    session: Any, pending_attr: Any, pending_var: str, pending_constrained: list | None,
    attrs: list,
) -> None:
    """Mutates `session` in place; never returns a response — the caller
    always falls through to STEP 5b/STEP 3 afterward, same as the
    original inline block.
    """
    _cpq_engine = _ask_api_module._cpq_engine
    logger = _ask_api_module.logger

    _is_grid_selector = pending_var in _cpq_engine.resolve_array_grid_links(attrs)
    _existing_picks = session.filled_multi.get(pending_var)
    if _existing_picks and _is_grid_selector:
        _still_allowed = (
            set(pending_constrained) if pending_constrained is not None else None
        )
        if _still_allowed is not None:
            session.filled_multi[pending_var] = [
                v for v in _existing_picks if v in _still_allowed
            ]
            session.display_filled[pending_var] = ", ".join(
                next((o.display_name for o in pending_attr.options
                      if o.item_value == v), v)
                for v in session.filled_multi[pending_var]
            ) or "(none)"
        if pending_var not in session.pending_grid_declined_vns:
            session.pending_grid_declined_vns.append(pending_var)
    else:
        session.filled_multi[pending_var] = []
        session.display_filled[pending_var] = "(none)"
    session.filled_source[pending_var] = "user"
    logger.info(
        "cpq: optional multi-select %r explicitly declined turn=%s",
        pending_var, session.turn,
    )
