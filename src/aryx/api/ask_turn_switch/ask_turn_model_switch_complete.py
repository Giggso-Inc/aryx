"""Completing a confirmed model switch inside one product family.

The model-level twin of `_complete_product_switch`: the session's answers are
saved under the outgoing model (the Product answer's item value) in
`session.model_snapshots`, then the incoming model's saved answers are put
back, or the answers start clean with the family and country kept. The new
Product value is then locked in. Restored values are re-checked by auto_fill on
the following turns, exactly as for a family switch. Gated by
`cpq_model_switch_snapshot_enabled` at the offer site, never here.
"""

from __future__ import annotations

from typing import Any

from aryx.cpq.catalog_profile import PRODUCT_LITERAL
from aryx.cpq.session_guard.session_guard import push_snapshot
from aryx.raven_log import raven_log, would_log

_MODEL_SNAPSHOT_CAP = 5


def _snapshot_session_answers(session: Any) -> dict[str, Any]:
    """Return a copy of the session's config answers for a model snapshot."""
    return {
        "filled": dict(session.filled),
        "filled_multi": dict(session.filled_multi),
        "display_filled": dict(session.display_filled),
        "filled_source": dict(session.filled_source),
        "negated_vns": list(session.negated_vns),
        "product_entity_id": session.product_entity_id,
        "model_leaf_resolved": bool(session.model_leaf_resolved),
    }


def _complete_model_switch(session: Any, new_value: str, new_display: str) -> None:
    """Save the current model's answers, restore or reset for the new model.

    Args:
        session: The live CpqSession; mutated in place.
        new_value: The new Product answer's item value (also the snapshot key).
        new_display: The new Product answer's display name.
    """
    from_value = session.filled.get(PRODUCT_LITERAL, "")
    push_snapshot(session, reason="model_switch")
    session.cascade_log.append({
        "event": "model_switch", "from": from_value, "to": new_value,
        "turn": getattr(session, "turn", None),
    })
    if from_value:
        # Re-inserted (not updated) so dict order tracks recency for the cap.
        session.model_snapshots.pop(from_value, None)
        session.model_snapshots[from_value] = _snapshot_session_answers(session)
        while len(session.model_snapshots) > _MODEL_SNAPSHOT_CAP:
            oldest = next(iter(session.model_snapshots))
            session.model_snapshots.pop(oldest)
            if would_log("DEBUG"):
                raven_log("DEBUG", "P4", "ask.model_switch.snapshot_evicted oldest model snapshot dropped at cap",
                          context={"reason_code": "SNAPSHOT_CAP_EXCEEDED", "evicted_model": oldest,
                                   "snapshot_cap": _MODEL_SNAPSHOT_CAP,
                                   "turn": getattr(session, "turn", None)})

    snap = session.model_snapshots.get(new_value)
    if snap:
        session.filled = dict(snap["filled"])
        session.filled_multi = dict(snap["filled_multi"])
        session.display_filled = dict(snap["display_filled"])
        session.filled_source = dict(snap["filled_source"])
        session.negated_vns = list(snap["negated_vns"])
        session.product_entity_id = snap["product_entity_id"]
        session.model_leaf_resolved = bool(snap.get("model_leaf_resolved", False))
    else:
        session.filled = {}
        session.filled_multi = {}
        session.display_filled = {}
        session.filled_source = {}
        session.negated_vns = []
        session.model_leaf_resolved = False
    session.filled[PRODUCT_LITERAL] = new_value
    session.display_filled[PRODUCT_LITERAL] = new_display
    session.filled_source[PRODUCT_LITERAL] = "user"
    session.pending_variables = []
    session.pending_model_leaf_candidates = []
    session.status = "configuring"
    session.pending_model_switch = ""
    session.pending_model_switch_display = ""
    session.pending_anchor = ""
    raven_log("INFO", "P4", "ask.model_switch.completed model switch committed", context={
        "selected_option": "restore_snapshot" if snap else "reset_config",
        "available_options": ["restore_snapshot", "reset_config"],
        "reason_code": "PRIOR_SNAPSHOT_FOUND" if snap else "NO_PRIOR_SNAPSHOT",
        "from_model": from_value, "to_model": new_value,
        "restored_filled_count": len(session.filled) if snap else 0,
        "snapshot_count": len(session.model_snapshots),
        "turn": getattr(session, "turn", None)})
