"""Top-level router for the mid-session product-switch pending-anchor
gate, split out of `_run_cpq_turn_inner` (Phase 10/11-phase ask_api
decomposition, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). A PRIOR
turn detected a different product than session.product_name and asked
the user to confirm before discarding the in-progress config; THIS
turn's raw reply is that yes/no answer, not a new CPQ hint (Andie-
planned fix for: "CPQ for two products is not working in the single
session"). Logic unchanged from the original inline if/elif/elif chain
— each anchor state is its own function in a sibling `ask_turn_*.py`
file purely to keep this file under the line cap.
"""

from __future__ import annotations

from typing import Any

from aryx.api.ask_turn_switch.ask_turn_confirm_switch_anchor import _handle_confirm_switch_anchor
from aryx.api.ask_turn_switch.ask_turn_suggest_switch_anchor import _handle_suggest_switch_anchor
from aryx.api.ask_turn_switch.ask_turn_switch_country_anchor import _handle_switch_country_anchor
from aryx.raven_log import raven_log


def _handle_product_switch_pending_anchor(
    req: "Any", session: Any, reader: Any, hints: dict,
) -> dict[str, Any] | None:
    """Returns a response dict when this turn's reply was consumed by the
    pending switch anchor; None when `session.pending_anchor` isn't one
    of the three switch-related states (or a branch fell through after
    resolving it), in which case the caller continues with the rest of
    the turn (STEP 1 onward) unchanged.
    """
    _anchor = session.pending_anchor
    raven_log("DEBUG", "P4", "ask.switch.gate product-switch pending anchor checked", context={
        "selected_option": _anchor if _anchor in ("switch_country", "suggest_switch", "confirm_switch")
        else "none",
        "available_options": ["switch_country", "suggest_switch", "confirm_switch", "none"],
        "reason_code": "PENDING_SWITCH_ANCHOR" if _anchor in (
            "switch_country", "suggest_switch", "confirm_switch") else "NO_SWITCH_ANCHOR",
        "pending_anchor": _anchor or "", "turn": session.turn,
        "pending_switch_product": getattr(session, "pending_switch_product", "") or ""})
    if session.pending_anchor == "switch_country":
        return _handle_switch_country_anchor(req, session, reader)
    if session.pending_anchor == "suggest_switch":
        return _handle_suggest_switch_anchor(req, session)
    if session.pending_anchor == "confirm_switch":
        return _handle_confirm_switch_anchor(req, session, reader, hints)
    return None
