"""Handling a router error/timeout from the top-level gateway call, split
out of `run_ask` (Phase 9/11-phase ask_api decomposition, docs/RAVEN_
STYLE_COMPLIANCE_PLAN_2026-09-03.md) purely to keep the sibling `ask_
run_ask.py` under the line cap. Logic unchanged from the original inline
block. `logger` and `_standard_ask_pipeline` are read through the
ask_api MODULE object (not imported by name) since ask_api tests patch
several of its own module-level names by dotted path.
"""

from __future__ import annotations

from typing import Any

from aryx.api import ask_standard_pipeline as _ask_standard_pipeline_module
from aryx.api.ask_response_building.ask_finish_cpq_result import _route_quote
from aryx.cpq.intent_gateway.intent_gateway import AskRouteDecision
from aryx.raven_log import raven_log


def _handle_router_error(
    req: "Any", reader: Any, route_meta: AskRouteDecision, mode: str,
    det_is_cpq: bool, soft_quote: bool,
) -> dict[str, Any]:
    from aryx.api import ask_api as _ask_api_module
    if mode == "shadow":
        # Shadow mode's whole point is "gateway is observe-only" — a
        # gateway FAILURE must not become customer-visible either; the
        # deterministic escape hatch stays exactly as it always has for
        # this mode.
        _ask_api_module.logger.warning(
            "cpq_router: escape_hatch mode=%s error=%r timed_out=%s "
            "det=%s soft_quote=%s → fallback",
            mode, route_meta.error, route_meta.timed_out, det_is_cpq, soft_quote,
        )
        from aryx.api.ask_run_ask import _route
        raven_log(
            "WARN", "P3", "ask.router.failed_surfaced gateway failed, deterministic fallback",
            error_code="ARYX_ASK_ROUTER_FAILED",
            context={"dependency_name": "oci_genai", "operation": "classify_ask_route",
                     "result": "error", "error_class": "timeout" if route_meta.timed_out else "error",
                     "attempt": 1, "recovery_selected": "deterministic_fallback",
                     "timed_out": bool(route_meta.timed_out), "det_is_cpq": det_is_cpq,
                     "soft_quote": soft_quote, "policy_version": mode},
        )
        _route("quote" if (det_is_cpq or soft_quote) else "standard", "ESCAPE_HATCH", mode)
        if det_is_cpq or soft_quote:
            return _route_quote(req, reader, route_meta)
        return _ask_standard_pipeline_module._standard_ask_pipeline(req, reader)
    # docs/CPQ_QUANTITY_COUNTRY_SUMMARY_FIXES_2026_08_13.md turn-1 unified
    # extraction plan — DELIBERATE, SCOPED departure from this codebase's
    # usual "never fail the turn, always degrade gracefully" convention,
    # for llm_first mode ONLY: once quantity/country extraction is fused
    # into this same call, a silent fallback here would mask a real LLM/
    # provider outage from both the customer and whoever's on call, since
    # routing AND extraction are now lost together. Explicitly NOT applied
    # to any other LLM call site in this codebase (see the plan doc).
    _ask_api_module.logger.error(
        "cpq_router: llm_first router failure surfaced to customer "
        "error=%r timed_out=%s",
        route_meta.error, route_meta.timed_out,
    )
    raven_log(
        "ERROR", "P2", "ask.router.failed_surfaced llm_first router failure shown to customer",
        error_code="ARYX_ASK_ROUTER_FAILED",
        context={"dependency_name": "oci_genai", "operation": "classify_ask_route",
                 "result": "error", "error_class": "timeout" if route_meta.timed_out else "error",
                 "attempt": 1, "recovery_selected": "customer_error",
                 "timed_out": bool(route_meta.timed_out), "policy_version": mode},
    )
    answer = (
        "Something went wrong processing your request — please try "
        "again in a moment."
    )
    return {
        "answer": answer, "terms": [], "tools_called": ["cpq_router_error()"],
        "usage": {"prompt_tokens": route_meta.prompt_tokens,
                  "completion_tokens": route_meta.completion_tokens,
                  "latency_ms": 0, "menial_model": route_meta.model_id or "cpq-engine",
                  "answer_model": route_meta.model_id or "cpq-engine"},
        "grounding": None, "session_data": req.session_data or {}, "cpq_payload": None,
    }
