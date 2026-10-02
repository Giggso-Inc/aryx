"""Identical-label change-request collision DETECTION for the
awaiting_approval/post_approval review status, split out of
`_run_cpq_turn_inner` (Phase 10/11-phase ask_api decomposition,
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Same reasoning as the
detect_attr_query collision check elsewhere, but scoped to change
requests (docs/CPQ_SESSION_2_OPEN_ISSUES.md item 2's fix never actually
covered this path — see detect_change_request_collision's own
docstring). Must run before detect_change_request, which would otherwise
silently resolve the tie to whichever attr is first in catalog order.
Logic unchanged from the original inline block. Every ask_api name below
is read through the module object (not imported by name) since tests
patch several of them by dotted path.
"""

from __future__ import annotations

from typing import Any

from aryx.api.ask_intent_queue_text_helpers import _queue_followup_note, _scan_and_enqueue_remaining_targets
from aryx.api import ask_core_helpers as _ask_core_helpers_module
from aryx.raven_log import raven_log


def _step6_change_collision_detect(
    req: "Any", session: Any, attrs: list,
) -> dict[str, Any] | None:
    """Returns a response dict when this turn's change request names an
    attr display_label shared by 2+ distinct attrs; None otherwise, in
    which case the caller continues with the rest of the STEP 6 routing.
    """
    from aryx.api import ask_api as _ask_api_module
    _cpq_engine = _ask_api_module._cpq_engine
    _change_collision = _cpq_engine.detect_change_request_collision(
        req.question, attrs, session.filled, filled_multi=session.filled_multi)
    if not _change_collision:
        return None
    _lines = "\n".join(
        f"{i}. **{a.variable_name}**"
        f"{f' (currently: {session.display_filled.get(a.variable_name)})' if session.display_filled.get(a.variable_name) else ''}"
        for i, a in enumerate(_change_collision, start=1)
    )
    answer = (
        f"There are {len(_change_collision)} different attributes labeled "
        f"**\"{_change_collision[0].display_label}\"** in this catalog — which one "
        f"did you mean to change? Reply with the number or the variable_name.\n\n{_lines}"
    )
    # Multi-target queue: scan the utterance for ALL other named valueless
    # change targets (excluding the collision candidates) and enqueue them
    # so none are silently dropped.
    _collision_vns = {a.variable_name for a in _change_collision}
    _scan_and_enqueue_remaining_targets(
        session, req.question, attrs, exclude_vns=_collision_vns,
    )
    answer += _queue_followup_note(session, attrs)
    session.pending_change_collision_vns = [a.variable_name for a in _change_collision]
    session.pending_change_collision_question = req.question
    raven_log("INFO", "P4", "ask.collision.change_detect which-attribute asked", context={
        "selected_option": "ask_which_attr", "available_options": ["ask_which_attr", "no_collision"],
        "reason_code": "CHANGE_LABEL_COLLISION", "candidate_vns": list(session.pending_change_collision_vns),
        "candidate_count": len(_change_collision),
        "display_label": getattr(_change_collision[0], "display_label", None),
        "answer_len": len(answer or ""), "turn": getattr(session, "turn", None)})
    _ask_core_helpers_module._persist_cpq_history(req.workspace_id, req.question, answer)
    return {
        "answer": answer, "terms": [], "tools_called": ["cpq_change_label_collision()"],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                  "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
        "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
    }
