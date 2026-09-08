"""Session restore/init, first-class UNDO, and the show-summary/
guided-mode shortcut gates — the very first section of
`_run_cpq_turn_inner`, split out as part of the pre-STEP-1 preamble
(Phase 10/11-phase ask_api decomposition, docs/RAVEN_STYLE_COMPLIANCE_
PLAN_2026-09-03.md). UNDO restores the last session snapshot before any
other routing UNLESS the message ALSO names a different real, ingested
product ("Actually go back to APX NEXT") — a snapshot replay cannot
honor that. The show-summary shortcut is checked early, before the
pending-anchor/pending-answer machinery and the LLM-first classifier
both get a chance to misfire on phrasing like "give the final summary
now". Logic unchanged from the original inline block. Every ask_api
name below is read through the module object (not imported by name)
since tests patch several of them by dotted path.
"""

from __future__ import annotations

import uuid
from typing import Any

from aryx.cpq.logging_context import set_run_id
from aryx.cpq.session_guard_loop import detect_guided_mode_accept, record_utterance
from aryx.cpq.session_guard_snapshot import (
    detect_undo,
    restore_last_snapshot,
    undo_empty_message,
    undo_success_message,
)
from aryx.cpq.state import CpqSession

from aryx.api import ask_api as _ask_api_module


def _preamble_init_session(req: "Any", reader: Any) -> "tuple[Any, str]":
    """Restores or initializes the session for this turn. Returns
    (session, incoming_pending_anchor) — the latter snapshotted BEFORE
    any anchor-resolution logic mutates it, since the universal LLM-first
    cutover later in the turn needs to know whether THIS turn started out
    answering a pending anchor question.
    """
    _cpq_engine = _ask_api_module._cpq_engine
    session = (
        CpqSession.from_dict(req.session_data)
        if req.session_data.get("mode") == "cpq"
        else CpqSession()
    )
    if not session.run_id:
        session.run_id = uuid.uuid4().hex
    set_run_id(session.run_id)
    session.turn += 1
    record_utterance(session, req.question)
    _incoming_pending_anchor = session.pending_anchor

    _ask_api_module._mine_history_for_cpq_context(session, req.history, _cpq_engine)
    return session, _incoming_pending_anchor


def _preamble_undo_gate(req: "Any", session: Any, reader: Any) -> dict[str, Any] | None:
    """Returns a response dict when this turn was a first-class UNDO;
    None otherwise, in which case the caller continues.
    """
    _is_undo = detect_undo(req.question)
    if not _is_undo:
        return None
    _undo_switch_target = _ask_api_module._safe_detect_product_mention(
        req.question, reader, req.workspace_id,
    )
    _is_product_switch_instead = bool(
        _undo_switch_target
        and _undo_switch_target.strip().lower() != session.product_name.strip().lower()
    )
    if _is_product_switch_instead:
        return None
    if restore_last_snapshot(session):
        answer = undo_success_message(session)
    else:
        answer = undo_empty_message()
    _ask_api_module._persist_cpq_history(req.workspace_id, req.question, answer)
    return {
        "answer": answer, "terms": [], "tools_called": ["cpq_undo()"],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                  "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
        "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
    }


def _preamble_shortcut_gates(req: "Any", session: Any, reader: Any) -> dict[str, Any] | None:
    """Handles the show-summary and guided-mode-accept shortcuts. Returns
    a response dict when either fired; None otherwise.
    """
    _cpq_engine = _ask_api_module._cpq_engine
    if (
        session.product_name
        and not session.pending_anchor
        and _cpq_engine.detect_show_summary_request(req.question)
    ):
        _summary_resp = _ask_api_module._build_show_summary_response(req, session, reader)
        if _summary_resp is not None:
            return _summary_resp

    if detect_guided_mode_accept(req.question) and not session.guided_mode:
        session.guided_mode = True
        session.unresolved_turns = 0
        answer = (
            "Guided mode is on — I'll ask one clear question at a time "
            "using the deterministic catalog flow (no free-form intent jumps)."
        )
        _ask_api_module._persist_cpq_history(req.workspace_id, req.question, answer)
        return {
            "answer": answer, "terms": [], "tools_called": ["cpq_guided_mode()"],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                      "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
            "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
        }
    return None
