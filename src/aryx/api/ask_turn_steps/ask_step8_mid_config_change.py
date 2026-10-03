"""Mid-configuration change request handling — the last pre-STEP-5 gate,
split out of `_run_cpq_turn_inner` (Phase 10/11-phase ask_api
decomposition, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md —
docs/CPQ_MID_CONFIG_CHANGE_REQUEST_PLAN.md). Change-request handling
used to be wired ONLY into the awaiting_approval/post_approval block —
a message like "change Is FedRamp or CCCS Required to None" sent while
OTHER fields were still pending fell through unrecognized and was
silently dropped (confirmed live, Amendment 22 follow-up). Reuses the
exact detectors + _handle_cascade the awaiting_approval path already
trusts; detect_change_request(s) already require the named attr to be in
session.filled, so a message about the CURRENTLY PENDING (not yet
answered) attr can never be misdetected here — it keeps falling through
to STEP 5 unchanged. Logic unchanged from the original inline block.
Every ask_api name below is read through the module object (not
imported by name) since tests patch several of them by dotted path.
"""

from __future__ import annotations

from typing import Any

from aryx.cpq.intent_schema.intent_schema_enums import IntentCategory

from aryx.api.ask_response_building.ask_build_no_value_response import _build_no_value_response
from aryx.api.ask_handle.ask_handle_cascade_multi import _handle_cascade_multi
from aryx.api.ask_intent_queue_text_helpers import _append_unmatched_targets_note, _scan_and_enqueue_remaining_targets
from aryx.api import ask_core_helpers as _ask_core_helpers_module
from aryx.api.ask_handle import ask_handle_cascade as _ask_handle_cascade_module
from aryx.api import ask_shadow_classify_and_confirm_intent as _ask_shadow_classify_and_confirm_intent_module
from aryx.raven_log import raven_log

_CHANGE_OPTIONS = ["mode_request_skip", "multi_change", "single_change", "change_no_value", "continue"]


def _step8_mid_config_change(
    req: "Any", session: Any, attrs: list, hiding_rules: list, rec_rules: list,
    con_rules: list, bml_eval: Any, catalog_prefix: str, mode_request: str | None,
) -> dict[str, Any] | None:
    """Returns a response dict when this turn was a mid-configuration
    change request; None otherwise, in which case the caller continues
    to STEP 5.
    """
    from aryx.api import ask_api as _ask_api_module
    logger = _ask_api_module.logger
    logger.info("cpq_step: mid_config_change_request_gate enter run_id=%s", session.run_id)
    if mode_request:
        raven_log("DEBUG", "P4", "ask.change.mid_config skipped for mode request", context={
            "selected_option": "mode_request_skip", "available_options": _CHANGE_OPTIONS,
            "reason_code": "MODE_REQUEST", "mode_request": mode_request,
            "turn": getattr(session, "turn", None)})
        return None
    _cpq_engine = _ask_api_module._cpq_engine

    _mc_multi_matches = _cpq_engine.detect_change_requests_multi(
        req.question, attrs, session.filled, filled_multi=session.filled_multi)
    if len(_mc_multi_matches) >= 2:
        raven_log("DEBUG", "P4", "ask.change.mid_config multi change detected", context={
            "selected_option": "multi_change", "available_options": _CHANGE_OPTIONS,
            "reason_code": "MULTI_CHANGE_REQUEST", "match_count": len(_mc_multi_matches),
            "changed_fields": [getattr(m[0], "variable_name", None)
                               for m in _mc_multi_matches if m][:25],
            "question_len": len(getattr(req, "question", None) or ""),
            "turn": getattr(session, "turn", None)})
        _scan_and_enqueue_remaining_targets(
            session, req.question, attrs,
            exclude_vns={a.variable_name for a, _ in _mc_multi_matches},
        )
        _mc_multi_result = _handle_cascade_multi(
            req, session, attrs, _mc_multi_matches,
            hiding_rules, rec_rules, con_rules,
        )
        raven_log("DEBUG", "P4", "ask.change.multi_cascade result", context={
            "selected_option": "multi_change" if _mc_multi_result is not None else "continue",
            "available_options": ["multi_change", "continue"],
            "reason_code": "CASCADE_HANDLED" if _mc_multi_result is not None else "CASCADE_NO_RESPONSE",
            "match_count": len(_mc_multi_matches), "turn": getattr(session, "turn", None)})
        if _mc_multi_result is not None:
            return _append_unmatched_targets_note(
                _mc_multi_result, req.question, attrs,
                {a.variable_name for a, _ in _mc_multi_matches},
            )
        return None

    _mc_change_result = _cpq_engine.detect_change_request(
        req.question, attrs, session.filled, filled_multi=session.filled_multi)
    if _mc_change_result and _ask_shadow_classify_and_confirm_intent_module._llm_confirm_deterministic_intent(
        req, session, attrs, IntentCategory.CHANGE_REQUEST,
        hiding_rules, rec_rules, con_rules, bml_eval, catalog_prefix,
        expected_variable_name=_mc_change_result[0].variable_name,
    ):
        _mc_changed_attr, _mc_new_value_hint = _mc_change_result
        raven_log("DEBUG", "P4", "ask.change.mid_config single change confirmed", context={
            "selected_option": "single_change", "available_options": _CHANGE_OPTIONS,
            "reason_code": "CHANGE_REQUEST_CONFIRMED",
            "changed_field": getattr(_mc_changed_attr, "variable_name", None),
            "has_value_hint": bool(_mc_new_value_hint),
            "question_len": len(getattr(req, "question", None) or ""),
            "turn": getattr(session, "turn", None)})
        _scan_and_enqueue_remaining_targets(
            session, req.question, attrs,
            exclude_vns={_mc_changed_attr.variable_name},
        )
        return _append_unmatched_targets_note(
            _ask_handle_cascade_module._handle_cascade(
                req, session, attrs, _mc_changed_attr, _mc_new_value_hint,
                hiding_rules, rec_rules, con_rules,
            ),
            req.question, attrs, {_mc_changed_attr.variable_name},
        )
    # Recognized change-verb naming an already-filled attr, but no
    # resolvable new value ("change hardware version") — ask which value;
    # also enqueues sibling targets on the intent queue.
    _mc_attr_no_value = _cpq_engine.detect_change_target_without_value(
        req.question, attrs, session.filled,
    )
    raven_log("DEBUG", "P4", "ask.change.mid_config no single change, value check", context={
        "selected_option": "change_no_value" if _mc_attr_no_value else "continue",
        "available_options": _CHANGE_OPTIONS,
        "reason_code": (
            "CHANGE_TARGET_WITHOUT_VALUE" if _mc_attr_no_value
            else "CHANGE_NOT_CONFIRMED" if _mc_change_result else "NO_CHANGE_REQUEST"),
        "single_detected_unconfirmed": bool(_mc_change_result),
        "target_field": getattr(_mc_attr_no_value, "variable_name", None),
        "turn": getattr(session, "turn", None)})
    if _mc_attr_no_value:
        _mc_nv_result = _build_no_value_response(
            req, session, attrs, _mc_attr_no_value, con_rules, bml_eval,
            "cpq_change_target_no_value",
        )
        _ask_core_helpers_module._persist_cpq_history(req.workspace_id, req.question, _mc_nv_result["answer"])
        return _mc_nv_result
    return None
