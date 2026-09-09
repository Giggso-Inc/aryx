"""Pending CHANGE-REQUEST label-collision resolution for the
awaiting_approval/post_approval review status, split out of
`_run_cpq_turn_inner` (Phase 10/11-phase ask_api decomposition,
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). A PRIOR turn asked
"which one did you mean?" (detect_change_request_collision) and stored
the candidates + original question; this turn's reply answers that, not
a fresh CPQ hint. Deterministic first (exact variable_name or 1-based
index), LLM fallback for looser phrasing (live-verified gap, PR #117).
Logic unchanged from the original inline block. Every ask_api name below
is read through the module object (not imported by name) since tests
patch several of them by dotted path.
"""

from __future__ import annotations

from typing import Any

from aryx.api.ask_intent_queue_text_helpers import _queue_followup_note
from aryx.api import ask_core_helpers as _ask_core_helpers_module
from aryx.api.ask_label_collision import ask_decline_reply_and_label_collision_llm as _ask_decline_reply_and_label_collision_llm_module
from aryx.api.ask_handle import ask_handle_cascade as _ask_handle_cascade_module


def _resolve_pending_change_collision(
    req: "Any", session: Any, attrs: list, hiding_rules: list, rec_rules: list,
    con_rules: list,
) -> dict[str, Any] | None:
    """Returns a response dict when this turn resolved (or was consumed
    by) a pending change-request label collision; None when there was no
    such pending collision, in which case the caller continues.
    """
    from aryx.api import ask_api as _ask_api_module
    _cpq_engine = _ask_api_module._cpq_engine
    if not session.pending_change_collision_vns:
        return None
    _resolved_vn = None
    _reply = req.question.strip()
    if _reply in session.pending_change_collision_vns:
        _resolved_vn = _reply
    elif _reply.isdigit():
        _idx = int(_reply) - 1
        if 0 <= _idx < len(session.pending_change_collision_vns):
            _resolved_vn = session.pending_change_collision_vns[_idx]
    if _resolved_vn is None:
        _candidates = [
            a for a in attrs
            if a.variable_name in session.pending_change_collision_vns
        ]
        if _candidates:
            _resolved_vn = _ask_decline_reply_and_label_collision_llm_module._llm_resolve_label_collision(
                _reply, _candidates, session, req.workspace_id)
    if _resolved_vn:
        _resolved_attr = next(
            (a for a in attrs if a.variable_name == _resolved_vn), None)
        _orig_question = session.pending_change_collision_question
        session.pending_change_collision_vns = []
        session.pending_change_collision_question = ""
        if _resolved_attr is not None:
            _resolved_change = _cpq_engine.detect_change_request(
                _orig_question, [_resolved_attr], session.filled,
                filled_multi=session.filled_multi)
            if _resolved_change:
                _, _resolved_value = _resolved_change
                return _ask_handle_cascade_module._handle_cascade(
                    req, session, attrs, _resolved_attr, _resolved_value,
                    hiding_rules, rec_rules, con_rules,
                )
            return _build_change_collision_no_value_response(
                req, session, attrs, _resolved_attr, _orig_question,
            )
    # Unrecognized reply — clear the stale pending state and fall through
    # to normal routing rather than getting stuck forever.
    session.pending_change_collision_vns = []
    session.pending_change_collision_question = ""
    return None


def _build_change_collision_no_value_response(
    req: "Any", session: Any, attrs: list, resolved_attr: Any, orig_question: str,
) -> dict[str, Any]:
    """No parseable value for the resolved attr (e.g. the original
    message's target was really a per-row quantity, not this attr's own
    value) — re-ask it as a genuine pending question, same as any other
    unanswered attr, so the NEXT reply is captured by STEP 5 instead of
    being orphaned (live-verified gap, 2026-07-22).
    """
    from aryx.api import ask_api as _ask_api_module
    _cpq_engine = _ask_api_module._cpq_engine
    opts_prompt = (
        _cpq_engine.next_question_prompt(resolved_attr, attrs=attrs)
        if resolved_attr.options else ""
    )
    answer = (
        f"Couldn't find a value for "
        f"**{_cpq_engine.disambiguated_label(resolved_attr, attrs)}** in "
        f"\"{orig_question}\". Please say what to change it to."
        + (f"\n\n{opts_prompt}" if opts_prompt else "")
        + _queue_followup_note(session, attrs)
    )
    session.status = "configuring"
    session.pending_variables = [
        resolved_attr.variable_name,
        *[v for v in session.pending_variables if v != resolved_attr.variable_name],
    ]
    _ask_core_helpers_module._persist_cpq_history(req.workspace_id, req.question, answer)
    return {
        "answer": answer, "terms": [],
        "tools_called": ["cpq_change_label_collision_resolved()"],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                  "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
        "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
    }
