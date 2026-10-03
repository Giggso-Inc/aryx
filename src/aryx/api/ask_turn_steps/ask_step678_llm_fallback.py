"""LLM fallback classifier for the awaiting_approval/post_approval
review status, split out of `_run_cpq_turn_inner` (Phase 10/11-phase
ask_api decomposition, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).
Every regex detector before this one found nothing — try the existing
menial-tier classifier before giving up (Andie scoping, 2026-07-22:
regex-first, LLM-fallback via the model tier already wired for term
extraction; no new model config). Reuses the exact same downstream
handlers as the regex path, so all their guardrails (real-value
validation, orphan quantity cleanup, single rule-loop pass) apply
identically. Logic unchanged from the original inline block. Every
ask_api name below is read through the module object (not imported by
name) since tests patch several of them by dotted path.
"""

from __future__ import annotations

from typing import Any

from aryx.api.ask_attr_recompute.ask_attr_query_and_classify_usage import _with_classify_usage
from aryx.api.ask_response_building.ask_build_no_value_response import _build_no_value_response
from aryx.api.ask_handle import ask_handle_cascade as _ask_handle_cascade_module
from aryx.api.ask_handle import ask_handle_multi_select_removal as _ask_handle_multi_select_removal_module
from aryx.api.ask_llm import ask_llm_classify_change_intent as _ask_llm_classify_change_intent_module
from aryx.raven_log import raven_log

_LLM_OPTIONS = ["removal", "cascade", "ask_value", "rejected", "none"]


def _step6_llm_fallback_classify(
    req: "Any", session: Any, attrs: list, hiding_rules: list, rec_rules: list,
    con_rules: list, bml_eval: Any,
) -> dict[str, Any] | None:
    """Returns a response dict when the menial-tier LLM classifier
    resolved a remove/change intent the regex detectors all missed;
    None otherwise, in which case the caller continues.
    """
    from aryx.api import ask_api as _ask_api_module
    _llm_intent, _ci_it, _ci_ot = _ask_llm_classify_change_intent_module._llm_classify_change_intent(
        req.question, attrs, session, req.workspace_id)
    if not _llm_intent:
        raven_log("DEBUG", "P4", "ask.change.llm_fallback no intent", context={
            "selected_option": "none", "available_options": _LLM_OPTIONS,
            "reason_code": "LLM_NO_VALID_INTENT", "input_tokens": _ci_it, "output_tokens": _ci_ot,
            "turn": getattr(session, "turn", None)})
        return None
    _llm_attr = next(
        (a for a in attrs if a.variable_name == _llm_intent["variable_name"]), None)
    _llm_kind = _llm_intent.get("intent") if isinstance(_llm_intent, dict) else None
    _llm_vn = _llm_intent.get("variable_name") if isinstance(_llm_intent, dict) else None
    _llm_has_value = bool(_llm_intent.get("value")) if isinstance(_llm_intent, dict) else False
    if _llm_attr is None:
        raven_log("DEBUG", "P4", "ask.change.llm_fallback rejected, attr not in catalog", context={
            "selected_option": "rejected", "available_options": _LLM_OPTIONS,
            "reason_code": "LLM_ATTR_NOT_IN_CATALOG", "intent": _llm_kind, "variable_name": _llm_vn,
            "turn": getattr(session, "turn", None)})
        return None
    if _llm_intent["intent"] == "remove":
        _cpq_engine = _ask_api_module._cpq_engine
        _current = session.filled_multi.get(_llm_attr.variable_name) or []
        _mentioned = _cpq_engine.apply_multi_answer(_llm_attr, _llm_intent["value"])
        _to_remove = [iv for iv, _dn in _mentioned if iv in _current]
        raven_log("DEBUG", "P4", "ask.change.llm_fallback remove intent", context={
            "selected_option": "removal" if _to_remove else "rejected",
            "available_options": _LLM_OPTIONS,
            "reason_code": "LLM_REMOVE_ACCEPTED" if _to_remove else "LLM_REMOVE_NOTHING_SELECTED",
            "intent": _llm_kind, "variable_name": _llm_vn,
            "mentioned_count": len(_mentioned or []), "remove_count": len(_to_remove),
            "turn": getattr(session, "turn", None)})
        if _to_remove:
            return _with_classify_usage(
                _ask_handle_multi_select_removal_module._handle_multi_select_removal(
                    req, session, attrs, _llm_attr, _to_remove,
                    hiding_rules, rec_rules, con_rules,
                ),
                _ci_it, _ci_ot,
            )
    elif _llm_intent["intent"] == "change":
        raven_log("DEBUG", "P4", "ask.change.llm_fallback change intent accepted", context={
            "selected_option": "cascade" if _llm_has_value else "ask_value",
            "available_options": _LLM_OPTIONS,
            "reason_code": "LLM_CHANGE_WITH_VALUE" if _llm_has_value else "LLM_CHANGE_NO_VALUE",
            "intent": _llm_kind, "variable_name": _llm_vn, "has_value": _llm_has_value,
            "input_tokens": _ci_it, "output_tokens": _ci_ot,
            "turn": getattr(session, "turn", None)})
        if not _llm_intent["value"]:
            # 2026-07-28 fix: the LLM correctly named the attribute
            # ("change the hardware type" -> the Hardware Version attr —
            # a match the regex label-mention check below can't see,
            # since "hardware type" doesn't literally contain "version")
            # but had nothing to set it to. Previously discarded entirely
            # (_validate required a nonempty value for every intent) —
            # the correctly-identified target attr was silently thrown
            # away instead of asking which value, the same live-verified
            # gap detect_change_target_without_value already fixes for
            # its own regex-matched targets.
            return _with_classify_usage(
                _build_no_value_response(
                    req, session, attrs, _llm_attr, con_rules, bml_eval,
                    "cpq_llm_change_target_no_value",
                ),
                _ci_it, _ci_ot,
            )
        return _with_classify_usage(_ask_handle_cascade_module._handle_cascade(
            req, session, attrs, _llm_attr, _llm_intent["value"],
            hiding_rules, rec_rules, con_rules,
        ), _ci_it, _ci_ot)
    else:
        raven_log("DEBUG", "P4", "ask.change.llm_fallback rejected, unknown intent", context={
            "selected_option": "rejected", "available_options": _LLM_OPTIONS,
            "reason_code": "LLM_INTENT_UNHANDLED", "intent": _llm_kind, "variable_name": _llm_vn,
            "turn": getattr(session, "turn", None)})
    return None
