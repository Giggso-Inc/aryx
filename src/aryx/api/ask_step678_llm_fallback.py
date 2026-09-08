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

from aryx.api.ask_attr_query_and_classify_usage import _with_classify_usage
from aryx.api.ask_build_no_value_response import _build_no_value_response
from aryx.api import ask_handle_cascade as _ask_handle_cascade_module
from aryx.api import ask_handle_multi_select_removal as _ask_handle_multi_select_removal_module
from aryx.api import ask_llm_classify_change_intent as _ask_llm_classify_change_intent_module


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
        return None
    _llm_attr = next(
        (a for a in attrs if a.variable_name == _llm_intent["variable_name"]), None)
    if _llm_attr is None:
        return None
    if _llm_intent["intent"] == "remove":
        _cpq_engine = _ask_api_module._cpq_engine
        _current = session.filled_multi.get(_llm_attr.variable_name) or []
        _mentioned = _cpq_engine.apply_multi_answer(_llm_attr, _llm_intent["value"])
        _to_remove = [iv for iv, _dn in _mentioned if iv in _current]
        if _to_remove:
            return _with_classify_usage(
                _ask_handle_multi_select_removal_module._handle_multi_select_removal(
                    req, session, attrs, _llm_attr, _to_remove,
                    hiding_rules, rec_rules, con_rules,
                ),
                _ci_it, _ci_ot,
            )
    elif _llm_intent["intent"] == "change":
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
    return None
