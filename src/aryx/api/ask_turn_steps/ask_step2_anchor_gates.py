"""STEP 2 product-config load plus the early anchor gates (mid-turn
switch re-detection, missing-country, empty-catalog), split out of
`_run_cpq_turn_inner` (Phase 10/11-phase ask_api decomposition,
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). session.product_name is
always set by this point (STEP 1 guarantees it) — load_product_config
may still overwrite it with the graph-resolved canonical name once the
product is actually loaded. session.pending_switch_question is captured
here only to seed productSelectionProduct_all; Region/Country hints from
that same original text are merged by the sibling catalog-hints step
AFTER this turn's own switch-redetection check runs, never here (see
that module's own docstring for the live-confirmed regression this
ordering avoids). Logic unchanged from the original inline block. Every
ask_api name below is read through the module object (not imported by
name) since tests patch several of them by dotted path.
"""

from __future__ import annotations

import time
from typing import Any

from aryx.api.ask_turn_switch.ask_turn_intent_diagnostics import _log_turn_intent_diagnostics
from aryx.api.ask_turn_switch.ask_turn_seed_product_anchor import _seed_product_select_from_anchor
from aryx.api.ask_turn_switch.ask_turn_switch_redetect import _check_mid_turn_switch_redetection

from aryx.api.ask_llm.ask_llm_confirm_extract_quantity import _build_llm_call_failed_response
from aryx.api import ask_core_helpers as _ask_core_helpers_module
from aryx.raven_log import raven_log

_GATE_OPTIONS = ["switch_redetect", "llm_call_failed", "ask_country", "empty_catalog", "continue"]


def _step2_resolve_product_and_gates(
    req: "Any", session: Any, reader: Any, hints: dict,
    product_was_anchored: bool, country_llm_call_failed: bool,
) -> "tuple[dict[str, Any] | None, list, str]":
    """Returns (early_response, attrs, switch_trigger_question).
    `early_response` is non-None when this turn is fully handled by one
    of the anchor gates (switch re-detection, missing country, or an
    empty catalog); the caller must return it immediately when present,
    in which case `attrs` is `[]` and `switch_trigger_question` is `""`.
    """
    from aryx.api import ask_api as _ask_api_module
    _cpq_engine = _ask_api_module._cpq_engine
    logger = _ask_api_module.logger

    _step2_t0 = time.monotonic()
    logger.info("cpq_step: step2_product_resolution start run_id=%s", session.run_id)
    product_name = session.product_name

    attrs, resolved_name = _cpq_engine.load_product_config(
        reader, req.workspace_id, product_name,
    )
    if resolved_name:
        session.product_name = resolved_name
    raven_log("DEBUG", "P4", "ask.preamble.product_config loaded", context={
        "product": product_name, "resolved_product": resolved_name or "",
        "renamed": bool(resolved_name and resolved_name != product_name),
        "attr_count": len(attrs or []), "turn": getattr(session, "turn", None),
        "duration_ms": int((time.monotonic() - _step2_t0) * 1000)})
    logger.info(
        "cpq_step: step2_product_resolution done run_id=%s elapsed_s=%.3f attrs=%d",
        session.run_id, time.monotonic() - _step2_t0, len(attrs),
    )

    _log_turn_intent_diagnostics(req, session, attrs)

    _seed_product_select_from_anchor(session, attrs)

    switch_trigger_question = session.pending_switch_question
    session.pending_switch_question = ""

    if product_was_anchored:
        _switch_redetect_response = _check_mid_turn_switch_redetection(
            req, session, reader, attrs, hints,
        )
        if _switch_redetect_response is not None:
            raven_log("INFO", "P4", "ask.preamble.gate switch re-detection handled the turn", context={
                "selected_option": "switch_redetect", "available_options": _GATE_OPTIONS,
                "reason_code": "MID_TURN_SWITCH_REDETECTED", "turn": getattr(session, "turn", None),
                "product": getattr(session, "product_name", None)})
            return _switch_redetect_response, [], ""

    if not session.country:
        if country_llm_call_failed:
            raven_log("WARN", "P3", "ask.preamble.gate country llm call failed", context={
                "selected_option": "llm_call_failed", "available_options": _GATE_OPTIONS,
                "reason_code": "COUNTRY_LLM_CALL_FAILED", "turn": getattr(session, "turn", None),
                "recovery_selected": "llm_call_failed_response", "result": "turn_ended"},
                error_code="ARYX_ASK_COUNTRY_LLM_FAILED")
            return _build_llm_call_failed_response(req, session), [], ""
        raven_log("INFO", "P4", "ask.preamble.gate destination country asked", context={
            "selected_option": "ask_country", "available_options": _GATE_OPTIONS,
            "reason_code": "COUNTRY_MISSING", "turn": getattr(session, "turn", None),
            "product": getattr(session, "product_name", None)})
        session.pending_anchor = "country"
        answer = (
            "Thanks — and what's the **destination country** for this "
            "quote? (e.g., *United States*, *Canada*, *Germany*)"
        )
        _ask_core_helpers_module._persist_cpq_history(req.workspace_id, req.question, answer)
        return {
            "answer": answer, "terms": [], "tools_called": ["cpq_anchor_validation()"],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                      "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
            "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
        }, [], ""

    session.pending_anchor = ""

    if not attrs:
        raven_log("WARN", "P3", "ask.preamble.gate empty catalog, falling back to standard ask", context={
            "selected_option": "empty_catalog", "available_options": _GATE_OPTIONS,
            "reason_code": "NO_CPQ_ATTRS", "turn": getattr(session, "turn", None),
            "product": getattr(session, "product_name", None),
            "recovery_selected": "standard_ask", "fallback_target": "standard_pipeline",
            "result": "fallback"}, error_code="ARYX_ASK_EMPTY_CATALOG")
        return {}, [], ""  # no CPQ data in graph — fall through to standard Ask

    raven_log("DEBUG", "P4", "ask.preamble.gate all anchor gates passed", context={
        "selected_option": "continue", "available_options": _GATE_OPTIONS,
        "reason_code": "ANCHOR_GATES_PASSED", "turn": getattr(session, "turn", None),
        "attr_count": len(attrs), "has_switch_trigger": bool(switch_trigger_question),
        "product_was_anchored": product_was_anchored})
    return None, attrs, switch_trigger_question
