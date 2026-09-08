"""Handling a decline (or ambiguous non-decline reply) to the
"confirm_switch" pending anchor, split out of `_run_cpq_turn_inner`
(Phase 10/11-phase ask_api decomposition, docs/RAVEN_STYLE_COMPLIANCE_
PLAN_2026-09-03.md) purely to keep the sibling `ask_turn_confirm_switch_
anchor.py` under the line cap. Logic unchanged from the original inline
block. `_cpq_engine`, `logger`, and `_persist_cpq_history` are read
through the ask_api MODULE object (not imported by name) since ask_api
tests patch several of its own module-level names by dotted path.
"""

from __future__ import annotations

from typing import Any

from aryx.api import ask_api as _ask_api_module


def _handle_confirm_switch_decline(
    req: "Any", session: Any, reader: Any, hints: dict,
) -> dict[str, Any]:
    """Before treating this as a flat decline, check whether the reply
    itself names a DIFFERENT real, ingested product — e.g. replying to
    "Switch to X?" with "Quote Y for a US customer" is not a decline,
    it's a new switch request that got swallowed (docs/CPQ_SESSION_2_
    OPEN_ISSUES.md item 1). Only re-prompt when the detected product
    differs from both the current product and the one just declined;
    otherwise fall through to a normal decline exactly as before.
    """
    _cpq_engine = _ask_api_module._cpq_engine
    _decline_alias_map = _cpq_engine.ingested_product_alias_map(reader, req.workspace_id)
    _redetected = _cpq_engine.detect_product_mention(
        req.question, hints, reader, req.workspace_id,
        alias_map=_decline_alias_map,
    )
    _old_pending = session.pending_switch_product
    if (
        _redetected
        and _redetected != session.product_name
        and _redetected != _old_pending
    ):
        session.pending_switch_product = _redetected
        session.pending_switch_question = req.question
        _ask_api_module.logger.info(
            "cpq_switch: decline-reply named a different product "
            "turn=%s old_pending=%r new_pending=%r",
            session.turn, _old_pending, _redetected,
        )
        answer = (
            f"It looks like you're asking about **{_redetected}**, but "
            f"this session is configuring **{session.product_name}**. "
            f"Switch to **{_redetected}** and discard the current "
            f"configuration? (yes/no)"
        )
        _ask_api_module._persist_cpq_history(req.workspace_id, req.question, answer)
        return {
            "answer": answer, "terms": [], "tools_called": ["cpq_switch_reoffer()"],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                      "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
            "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
        }
    session.pending_switch_product = ""
    session.pending_switch_question = ""
    session.pending_anchor = ""
    _ask_api_module.logger.info(
        "cpq_switch: declined turn=%s staying on product=%r",
        session.turn, session.product_name,
    )
    answer = f"OK — continuing with **{session.product_name}**."
    _ask_api_module._persist_cpq_history(req.workspace_id, req.question, answer)
    return {
        "answer": answer, "terms": [], "tools_called": ["cpq_switch_declined()"],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                  "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
        "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
    }
