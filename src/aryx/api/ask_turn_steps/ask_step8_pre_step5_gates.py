"""Orchestrator for the pre-STEP-5 gates: response-mode detection, label
collision/attr-query/free-text-constraint, STEP 7 strict Q&A + pending
system-initiated collision, and mid-configuration change requests —
split out of `_run_cpq_turn_inner` (Phase 10/11-phase ask_api
decomposition, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).
`mode_request` is detected early here — before STEP 5's answer-locking —
so an explicit JSON/batch request always wins over being misread as an
invalid answer to the pending attr; it is returned alongside any early
response since STEP 5 and the response-building tail both consult it
too. Logic and stage order unchanged from the original inline block.
"""

from __future__ import annotations

from typing import Any

from aryx.api.ask_turn_steps.ask_step8_label_and_query import _step8_label_collision_and_query
from aryx.api.ask_turn_steps.ask_step8_mid_config_change import _step8_mid_config_change
from aryx.api.ask_turn_steps.ask_step8_qa_and_collision import _step8_qa_and_pending_collision
from aryx.raven_log import raven_log

_GATE_OPTIONS = ["label_collision_or_query", "qa_or_pending_collision", "mid_config_change", "continue"]


def _log_gate_handled(session: Any, gate: str, mode_request: str | None, result: dict) -> None:
    """INFO milestone: one pre-STEP-5 gate handled the whole turn."""
    raven_log("INFO", "P4", "ask.preamble.gate pre-step5 gate handled the turn", context={
        "selected_option": gate, "available_options": _GATE_OPTIONS,
        "reason_code": "GATE_HANDLED", "mode_request": mode_request,
        "tools_called": list((result or {}).get("tools_called") or [])[:5],
        "turn": getattr(session, "turn", None)})


def _step8_run_pre_step5_gates(
    req: "Any", session: Any, attrs: list, reader: Any, hiding_rules: list,
    rec_rules: list, con_rules: list, validation_rules: list, bml_eval: Any,
    catalog_prefix: str,
) -> "tuple[dict[str, Any] | None, str | None]":
    """Returns (early_response, mode_request). `early_response` is
    non-None when this turn is fully handled by one of these gates; the
    caller must return it immediately when present. `mode_request` is
    always returned since STEP 5 and beyond consult it too.
    """
    from aryx.api import ask_api as _ask_api_module
    _cpq_engine = _ask_api_module._cpq_engine
    mode_request = _cpq_engine.detect_response_mode_request(req.question)
    raven_log("DEBUG", "P4", "ask.preamble.mode_request response mode detected", context={
        "selected_option": mode_request or "none", "available_options": ["json", "batch", "none"],
        "reason_code": "MODE_REQUESTED" if mode_request else "NO_MODE_REQUEST",
        "turn": getattr(session, "turn", None)})

    result = _step8_label_collision_and_query(
        req, session, attrs, validation_rules, con_rules, bml_eval, mode_request,
    )
    if result is not None:
        _log_gate_handled(session, "label_collision_or_query", mode_request, result)
        return result, mode_request

    result = _step8_qa_and_pending_collision(
        req, session, attrs, reader, hiding_rules, rec_rules, con_rules, bml_eval,
        catalog_prefix, mode_request,
    )
    if result is not None:
        _log_gate_handled(session, "qa_or_pending_collision", mode_request, result)
        return result, mode_request

    result = _step8_mid_config_change(
        req, session, attrs, hiding_rules, rec_rules, con_rules, bml_eval,
        catalog_prefix, mode_request,
    )
    if result is not None:
        _log_gate_handled(session, "mid_config_change", mode_request, result)
        return result, mode_request

    raven_log("DEBUG", "P4", "ask.preamble.gate no pre-step5 gate handled the turn", context={
        "selected_option": "continue", "available_options": _GATE_OPTIONS,
        "reason_code": "NO_GATE_MATCHED", "mode_request": mode_request,
        "turn": getattr(session, "turn", None)})
    return None, mode_request
