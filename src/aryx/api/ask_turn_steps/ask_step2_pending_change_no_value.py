"""Resolving a pending "which value?" clarifying question left over from
a previous turn's valueless change request, split out of
`_run_cpq_turn_inner` (Phase 10/11-phase ask_api decomposition,
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md — docs/CPQ_MID_CONFIG_
CHANGE_REQUEST_PLAN.md Related finding 1). The reply IS the new value
directly, not a fresh hint, so it must be captured before any other
detection runs, regardless of session.status — same reasoning as the
pending_change_collision_vns/pending_label_collision_vns checks
elsewhere. Logic unchanged from the original inline block. Every
ask_api name below is read through the module object (not imported by
name) since tests patch several of them by dotted path.
"""

from __future__ import annotations

from typing import Any

from aryx.api.ask_scope_and_pending.ask_change_decline_and_scope_memory import _constrain_excluding_rejected, _extract_replacement_clause, _is_change_value_decline
from aryx.api.ask_label_collision.ask_decline_reply_and_label_collision_llm import _is_decline_reply
from aryx.api.ask_llm.ask_llm_topic_switch_and_change_decline import _pending_reply_is_topic_switch
from aryx.api import ask_core_helpers as _ask_core_helpers_module
from aryx.api.ask_handle import ask_handle_cascade as _ask_handle_cascade_module
from aryx.raven_log import raven_log

_PCNV_OPTIONS = ["attr_not_found", "topic_switch", "decline", "cascade"]


def _resolve_pending_change_no_value(
    req: "Any", session: Any, attrs: list, hiding_rules: list, rec_rules: list,
    con_rules: list, bml_eval: Any,
) -> dict[str, Any] | None:
    """Returns a response dict when this turn resolved (or was consumed
    by) a pending change-no-value clarification; None when there was no
    such pending state, in which case the caller continues.
    """
    from aryx.api import ask_api as _ask_api_module
    if not session.pending_change_no_value_vn:
        return None
    logger = _ask_api_module.logger
    _cpq_engine = _ask_api_module._cpq_engine
    _pcnv_attr = next(
        (a for a in attrs if a.variable_name == session.pending_change_no_value_vn), None,
    )
    _pcnv_vn = session.pending_change_no_value_vn
    session.pending_change_no_value_vn = ""
    _pcnv_found = _pcnv_attr is not None
    # Same topic-switch gap as STEP 5's pending-answer lock (docs/
    # CPQ_PENDING_TOPIC_SWITCH_PLAN_2026_08_11.md), but on this earlier,
    # separate "which value?" pending mechanism — confirmed live
    # 2026-08-11: with Hardware Version pending here, "First i wanted to
    # changed Wireless Carrier" has no _CHANGE_VERB_RE match ("changed"
    # isn't "change"/"changing") and named a DIFFERENT real attr in plain
    # language, but this block had no topic-switch check of its own — it
    # forced the whole message into `_handle_cascade` as a literal
    # (failing) new value for Hardware Version, producing "I couldn't
    # match that to a valid option for Hardware Version." Falls through
    # to normal routing (identical to the STEP 5 fix) whenever the LLM
    # confidently identifies a different real target.
    if _pcnv_attr and _pending_reply_is_topic_switch(
        req.question, _pcnv_attr, attrs, session.filled,
        session.filled_multi, req.workspace_id,
    ):
        _pcnv_attr = None
    if not _pcnv_attr:
        _pcnv_why = "topic_switch" if _pcnv_found else "attr_not_found"
        raven_log("DEBUG", "P4", "ask.change.pending_no_value released, normal routing", context={
            "selected_option": _pcnv_why, "available_options": _PCNV_OPTIONS,
            "reason_code": "PENDING_REPLY_TOPIC_SWITCH" if _pcnv_found else "PENDING_ATTR_NOT_IN_CATALOG",
            "variable_name": _pcnv_vn, "turn": getattr(session, "turn", None),
            "reply_len": len(getattr(req, "question", "") or "")})
        return None
    # QA issue #3: re-derive constrained set for scoped match/retry.
    # §15: try/except so pure declines never crash on rule engine.
    try:
        _pcnv_constrained = _cpq_engine.apply_constraint_rules(
            attrs, con_rules, session.filled, bml_eval, filled_multi=session.filled_multi,
        ).get(_pcnv_attr.entity_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "cpq: constraint recompute failed for pending change "
            "value on %r, proceeding unconstrained: %r",
            _pcnv_attr.variable_name, exc,
        )
        raven_log("WARN", "P3", "ask.change.pending_no_value constraint recompute failed, unconstrained", context={
            "variable_name": _pcnv_vn, "turn": getattr(session, "turn", None),
            "triggering_error": type(exc).__name__, "attempt": 1, "max_attempts": 1,
            "backoff_ms": 0, "recovery_selected": "proceed_unconstrained",
            "fallback_target": "unconstrained_options", "exit_condition": "single_attempt",
            "result": "degraded"}, error_code="ARYX_ASK_PCNV_CONSTRAINT_FAILED")
        _pcnv_constrained = None
    # PROMPT 6: extract wanted (+ rejected); exclude rejected option.
    _pcnv_wanted, _pcnv_rejected = _extract_replacement_clause(req.question)
    _pcnv_match_text = _pcnv_wanted or req.question
    _pcnv_constrained = _constrain_excluding_rejected(
        _pcnv_attr, _pcnv_rejected, _pcnv_constrained,
    )
    # QA issue #2: try real value FIRST; only treat as decline when
    # nothing resolves (compound "don't want Standard; use Premium").
    if _pcnv_attr.select_type == "multi":
        _pcnv_matched = bool(_cpq_engine.apply_multi_answer(
            _pcnv_attr, _pcnv_match_text, _pcnv_constrained,
        ))
    else:
        _pcnv_matched = _cpq_engine.apply_answer(
            _pcnv_attr, _pcnv_match_text, _pcnv_constrained,
        ) is not None
    _pcnv_current = session.display_filled.get(_pcnv_attr.variable_name)
    if not _pcnv_matched and _is_decline_reply(
        req.question, _cpq_engine.disambiguated_label(_pcnv_attr, attrs),
        _pcnv_current or "", req.workspace_id,
        deterministic_hit=_is_change_value_decline(req.question),
    ):
        # docs/CPQ_REGEX_VS_LLM_ANCHOR_GUARDRAIL_AUDIT_2026_08_12.md row
        # 15-16: LLM fallback added for decline phrasing the
        # deterministic regex doesn't cover.
        answer = (
            f"No problem — I'll leave "
            f"**{_cpq_engine.disambiguated_label(_pcnv_attr, attrs)}** "
            f"as it is"
            + (f" (**{_pcnv_current}**)." if _pcnv_current else ".")
        )
        raven_log("INFO", "P4", "ask.change.pending_no_value declined, value kept", context={
            "selected_option": "decline", "available_options": _PCNV_OPTIONS,
            "reason_code": "CHANGE_VALUE_DECLINED", "variable_name": _pcnv_vn,
            "has_current_value": bool(_pcnv_current), "turn": getattr(session, "turn", None)})
        _ask_core_helpers_module._persist_cpq_history(req.workspace_id, req.question, answer)
        return {
            "answer": answer, "terms": [], "tools_called": ["cpq_change_declined()"],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                      "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
            "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
        }
    # Multi-intent follow-up (docs/CPQ_LLM_INTENT_FIRST_PLAN.md Fix 4) is
    # now handled INSIDE _handle_cascade itself — it's the single common
    # convergence point every change-request entry point reaches, so
    # re-queuing pending_multi_intent_vn there covers this caller too
    # without needing its own copy here.
    raven_log("DEBUG", "P4", "ask.change.pending_no_value reply routed to cascade", context={
        "selected_option": "cascade", "available_options": _PCNV_OPTIONS,
        "reason_code": "VALUE_MATCHED" if _pcnv_matched else "NO_MATCH_NOT_DECLINE",
        "variable_name": _pcnv_vn, "select_type": getattr(_pcnv_attr, "select_type", None),
        "matched": bool(_pcnv_matched), "has_rejected_clause": bool(_pcnv_rejected),
        "constrained_count": len(_pcnv_constrained) if isinstance(_pcnv_constrained, (list, set, tuple, dict)) else None,
        "turn": getattr(session, "turn", None)})
    return _ask_handle_cascade_module._handle_cascade(
        req, session, attrs, _pcnv_attr, _pcnv_match_text,
        hiding_rules, rec_rules, con_rules,
        constrained_item_values=_pcnv_constrained,
    )
