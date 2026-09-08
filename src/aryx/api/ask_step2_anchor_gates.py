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

from aryx.api.ask_turn_intent_diagnostics import _log_turn_intent_diagnostics
from aryx.api.ask_turn_seed_product_anchor import _seed_product_select_from_anchor
from aryx.api.ask_turn_switch_redetect import _check_mid_turn_switch_redetection

from aryx.api.ask_llm_confirm_extract_quantity import _build_llm_call_failed_response
from aryx.api import ask_core_helpers as _ask_core_helpers_module


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
            return _switch_redetect_response, [], ""

    if not session.country:
        if country_llm_call_failed:
            return _build_llm_call_failed_response(req, session), [], ""
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
        return {}, [], ""  # no CPQ data in graph — fall through to standard Ask

    return None, attrs, switch_trigger_question
