"""STEP 5 responses for an unresolved pending answer — a low-confidence
LLM pick between real options, or a plain no-match — split out of
`_run_cpq_turn_inner` (Phase 10/11-phase ask_api decomposition,
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). The low-confidence
case (Gap A/Amendment 2) must not silently commit — a judgment call
between real options, not hallucination, same "never guess a real
decision" discipline as an ambiguous label collision. The plain-miss
case is a SCOPED re-ask (PROMPT 7): never fall through to
next_question_prompt without constrained_item_values, which dumped the
full 325-option Product list after a constrained family list (live:
r7ex). Logic unchanged from the original inline block. Every ask_api
name below is read through the module object (not imported by name)
since tests patch several of them by dotted path.
"""

from __future__ import annotations

from typing import Any

from aryx.cpq.pending_scope import log_scope_lost, set_pending_scope

from aryx.api.ask_scope_and_pending.ask_change_decline_and_scope_memory import _remember_attr_scope
from aryx.api.ask_label_collision.ask_label_collision_detect_and_compose import _compose_disambiguation_question
from aryx.api.ask_scope_and_pending.ask_scope_reask_responses import _scoped_reask_response
from aryx.api import ask_core_helpers as _ask_core_helpers_module


def _step9_low_confidence_response(
    req: "Any", session: Any, attrs: list, pending_attr: Any, pending_var: str,
    llm_low_confidence_candidates: list,
) -> dict[str, Any]:
    from aryx.api import ask_api as _ask_api_module
    _cpq_engine = _ask_api_module._cpq_engine
    _pending_label = _cpq_engine.disambiguated_label(pending_attr, attrs)
    set_pending_scope(
        session,
        kind="attr_options",
        candidates=list(llm_low_confidence_candidates),
        origin_question=req.question,
        attr_vn=pending_var,
        asked_turn=session.turn,
    )
    _lines = "\n".join(f"- {c}" for c in llm_low_confidence_candidates)
    _static_answer = (
        f"I'm not certain which option you meant for "
        f"**{_pending_label}** — could you confirm which one?\n\n{_lines}"
    )
    answer = _compose_disambiguation_question(
        req.question, f"which value they meant for {_pending_label}",
        llm_low_confidence_candidates,
        {"Country": session.country, "Product": session.product_name},
        _static_answer, req.workspace_id,
    )
    _ask_core_helpers_module._persist_cpq_history(req.workspace_id, req.question, answer)
    return {
        "answer": answer, "terms": [], "tools_called": ["cpq_low_confidence_answer()"],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                  "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
        "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
    }


def _step9_options_miss_response(
    req: "Any", session: Any, attrs: list, pending_attr: Any, pending_var: str,
    pending_constrained: list | None,
) -> dict[str, Any]:
    from aryx.api import ask_api as _ask_api_module
    _cpq_engine = _ask_api_module._cpq_engine
    _pending_label = _cpq_engine.disambiguated_label(pending_attr, attrs)
    if not session.pending_scope_candidates or (
        session.pending_scope_attr_vn
        and session.pending_scope_attr_vn != pending_var
    ):
        _remember_attr_scope(
            session, pending_attr, pending_constrained, req.question,
        )
    if session.pending_scope_candidates:
        return _scoped_reask_response(
            req, session, req.question,
            scope_label=_pending_label,
            tools_called="cpq_invalid_answer()",
        )
    log_scope_lost(
        run_id=session.run_id or "",
        reply=req.question,
        reason="invalid_answer_no_scope",
    )
    opts_prompt = _cpq_engine.next_question_prompt(
        pending_attr, "", pending_constrained, attrs=attrs,
    )
    _remember_attr_scope(
        session, pending_attr, pending_constrained, req.question,
    )
    answer = (
        f"I didn't recognise **\"{req.question.strip()}\"** as a valid "
        f"choice for **{_pending_label}**. Please pick one:\n\n{opts_prompt}"
    )
    _ask_core_helpers_module._persist_cpq_history(req.workspace_id, req.question, answer)
    return {
        "answer": answer, "terms": [], "tools_called": ["cpq_invalid_answer()"],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                  "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
        "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
    }
