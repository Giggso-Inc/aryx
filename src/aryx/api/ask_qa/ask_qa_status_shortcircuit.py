"""Short-circuiting a session-status meta-question ("what's next") to the
pending question itself, split out of `_handle_cpq_qa` (Phase 8/11-phase
ask_api decomposition, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md)
purely to keep the sibling `ask_handle_cpq_qa.py` under the line cap.
Logic unchanged from the original inline block. `_cpq_engine` and
`_persist_cpq_history` are read through the ask_api MODULE object (not
imported by name) since ask_api tests patch several of its own
module-level names by dotted path.
"""

from __future__ import annotations

from typing import Any

from aryx.api import ask_core_helpers as _ask_core_helpers_module
from aryx.api.ask_llm import ask_llm_classify_intent_universal as _ask_llm_classify_intent_universal_module
from aryx.cpq.intent_schema.intent_schema import Confidence, IntentCategory
from aryx.raven_log import raven_log


def _log_status(session: Any, opt: str, reason: str, meta: Any = None, level: str = "DEBUG", **ctx: Any) -> None:
    """One raven record per status short-circuit branch (never question/answer text)."""
    raven_log(level, "P4", f"ask.qa.status_shortcircuit {'fired' if opt == 'short_circuit' else 'skipped'}",  # type: ignore[arg-type]
              context={"selected_option": opt, "available_options": ["short_circuit", "continue_qa"],
                       "reason_code": reason, "turn": getattr(session, "turn", None),
                       "run_id": getattr(session, "run_id", None), "road": "qa",
                       "intent_category": str(getattr(meta, "category", None)),
                       "confidence": str(getattr(meta, "confidence", None)), **ctx})


def _qa_status_shortcircuit(
    req: "Any", session: Any, attrs: list, resume_review: bool,
) -> "tuple[dict[str, Any] | None, Any, int, int]":
    """docs/CPQ_QA_RESUME_CONCATENATION_PLAN_2026_08_18.md — a session-
    status meta-question ("what's next") while something is genuinely
    pending IS answered by the pending question itself; querying the
    graph for it only produces irrelevant, hallucinated noise glued to
    the correct resume reminder (live-confirmed). Skip the graph-QA path
    entirely in this narrow case — everything else in the caller is
    unchanged.

    LLM-based, not regex/pattern-matched: a fixed phrase-list under-
    generalizes across phrasing variants it was never written for.
    Reuses the SAME classifier `_llm_classify_intent_universal` the
    caller already calls further along for its (flag-gated) ambiguity
    check -- no new LLM integration. Gated on `session.pending_variables`
    so the extra call only happens when a short-circuit could even apply.

    Returns (response_or_none, meta_result, meta_prompt_tokens,
    meta_completion_tokens) — the caller must reuse `meta_result`/its
    token counts for its own (flag-gated) ambiguity check instead of
    re-classifying the same arguments a second time on the same turn
    (PR #213 review finding), regardless of whether this short-circuit
    fired.
    """
    from aryx.api import ask_api as _ask_api_module
    if resume_review or not session.pending_variables:
        _log_status(session, "continue_qa", "RESUME_REVIEW" if resume_review else "NOTHING_PENDING")
        return None, None, 0, 0
    _meta_result, _meta_it, _meta_ot = _ask_llm_classify_intent_universal_module._llm_classify_intent_universal(
        req.question, attrs, session, req.workspace_id,
    )
    if not (
        _meta_result is not None
        and _meta_result.category == IntentCategory.SESSION_STATUS_QUERY
        and _meta_result.confidence != Confidence.LOW
    ):
        _log_status(session, "continue_qa", "NO_CLASSIFICATION" if _meta_result is None
                    else "NOT_CONFIDENT_STATUS_QUERY", _meta_result)
        return None, _meta_result, _meta_it, _meta_ot
    _meta_pending_attr = next(
        (a for a in attrs if a.variable_name == session.pending_variables[0]), None,
    )
    if not _meta_pending_attr:
        _log_status(session, "continue_qa", "PENDING_ATTR_NOT_FOUND", _meta_result)
        return None, _meta_result, _meta_it, _meta_ot
    answer = (
        "*Resuming your configuration...*\n\n"
        + _ask_api_module._cpq_engine.next_question_prompt(_meta_pending_attr, attrs=attrs)
    )
    _log_status(session, "short_circuit", "SESSION_STATUS_QUERY", _meta_result, "INFO",
                pending_vn=getattr(_meta_pending_attr, "variable_name", None),
                prompt_tokens=_meta_it, completion_tokens=_meta_ot, answer_len=len(answer))
    _ask_core_helpers_module._persist_cpq_history(req.workspace_id, req.question, answer)
    return {
        "answer": answer, "terms": [], "tools_called": ["cpq_qa_status()"],
        "usage": {"prompt_tokens": _meta_it, "completion_tokens": _meta_ot,
                  "latency_ms": 0, "menial_model": "cpq-qa",
                  "answer_model": "cpq-qa"},
        "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
    }, _meta_result, _meta_it, _meta_ot
