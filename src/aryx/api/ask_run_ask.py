"""Top-level Ask pipeline entry point, split out of `api/ask_api.py`
(Phase 9/11-phase ask_api decomposition, docs/RAVEN_STYLE_COMPLIANCE_
PLAN_2026-09-03.md). Logic unchanged from the original inline
definition. `_reader`, `logger`, `get_settings`, `_llm_classify_is_cpq_
question`, `_standard_ask_pipeline`, `_deterministic_cpq_gate`,
`classify_ask_route`, `mark_top_level_route_used`, `hard_off_topic`, and
`soft_quote_heuristic` are read through the ask_api MODULE object (not
imported by name) since ask_api tests patch several of its own
module-level names by dotted path.
"""

from __future__ import annotations

import dataclasses
import contextvars
from typing import Any

from aryx.raven_log import raven_log
from aryx.api.ask_llm.ask_llm_classify_is_cpq_question import _llm_classify_is_cpq_question
from aryx.api import ask_core_helpers as _ask_core_helpers_module
from aryx.api.ask_attribute_followup import _attribute_followup_or_forget
from aryx.api.ask_attribute_search import _route_attribute_search
from aryx.api.ask_feature_region_search import _route_feature_region_search
from aryx.api.ask_response_building import ask_finish_cpq_result as _ask_finish_cpq_result_module
from aryx.api import ask_standard_pipeline as _ask_standard_pipeline_module
from aryx.api.ask_response_building.ask_finish_cpq_result import _route_quote
from aryx.api.ask_request_models import AskRequest
from aryx.api.ask_qa.ask_route_qa import _route_ambiguous, _route_qa
from aryx.api.ask_run_ask_router_error import _handle_router_error

# Road taken by the latest run_ask in this context; read by submit_message (R1).
_last_road: contextvars.ContextVar[str] = contextvars.ContextVar("ask_last_road", default="")
_ROADS = ["quote", "attribute_search", "qa", "standard", "feature_search", "ambiguous"]


_last_step: contextvars.ContextVar[str] = contextvars.ContextVar("ask_last_step", default="")


def note_step(name: str) -> None:
    """Remember the latest turn step entered (read by the turn.failed record)."""
    _last_step.set(name)


def current_step() -> str:
    """Return the last turn step entered in this context ('' when none)."""
    return _last_step.get()


def current_road() -> str:
    """Return the road run_ask handed the turn to ('' when none yet)."""
    return _last_road.get()


def _route(selected: str, reason: str, mode: str, **extra: Any) -> None:
    """Record the route decision (R4) and remember the road for the turn record."""
    _last_road.set(selected)
    raven_log("INFO", "P4", "ask.route.selected road chosen", context={
        "selected_option": selected, "available_options": _ROADS,
        "reason_code": reason, "policy_version": mode, **extra,
    })


def run_ask(req: AskRequest) -> dict[str, Any]:
    """Execute the Aryx Ask pipeline for a request payload.

    Prompt 3 — inverted router (config-reversible):
      ARYX_CPQ_INTENT_MODE=
        llm_first          — gateway routes every cold-start turn
        deterministic_first — legacy is_cpq_question gate only
        shadow (default)   — deterministic decides; gateway logs agreement

    Live CPQ sessions always enter _run_cpq_turn (session owns state).
    BOM payloads still only come from auto_fill → rule loop → build_payload.
    """
    from aryx.api import ask_api as _ask_api_module
    reader = _ask_core_helpers_module._reader(req.workspace_id)
    settings = _ask_api_module.get_settings()
    mode = (settings.cpq_intent_mode or "shadow").strip().lower()
    # Attribute-first discovery: a reply to "which value?" (ask_attribute_followup.py).
    followup, req = _attribute_followup_or_forget(req, reader)
    if followup is not None:
        return followup
    # ISSUE-001: `mode == "cpq"` is a dataclass default on EVERY CpqSession,
    # so it can't signal a live quote -- `product_name` is only set once a
    # real quote begins, the genuine "is a quote actually in progress" signal.
    # PR #205 review fix (High finding #3): also check `pending_anchor`
    # (set when product-family detection FAILS, i.e. precisely when
    # `product_name` is NOT yet set) so a reply to that disambiguation isn't
    # misrouted as a fresh cold-start turn. Defaults to `""` (falsy) on a
    # genuinely fresh session, so this is a safe, zero-cost addition.
    live_session = bool(req.session_data.get("product_name")) or bool(
        req.session_data.get("pending_anchor"),
    )

    # ── Live session: always CPQ turn (engine owns switch/undo/cascade) ─────
    # N3: switch confirmation stays inside _run_cpq_turn — log explicit hint.
    if live_session:
        _ask_api_module.logger.info(
            "cpq_router: live_session product=%r status=%r — skip top-level route",
            req.session_data.get("product_name"),
            req.session_data.get("status"),
        )
        _route("quote", "LIVE_SESSION", mode)
        return _route_quote(req, reader)

    raven_log("DEBUG", "P4", "ask.route.check live_session=false", context={
        "check": "live_session", "result": False, "policy_version": mode,
        "question_len": len(req.question or ""), "history_len": len(req.history or []),
    })
    # N10: hard off-topic before any mode work (no LLM, no CPQ).
    if _ask_api_module.hard_off_topic(req.question):
        _ask_api_module.logger.info("cpq_router: hard_off_topic → standard Ask")
        _route("standard", "HARD_OFF_TOPIC", mode)
        return _ask_standard_pipeline_module._standard_ask_pipeline(req, reader)

    # Feature/region product search (2026-09-16) -- deterministic, narrow
    # regex trigger, checked before any CPQ/gateway work so it never
    # competes with or consumes the top-level gateway's one-LLM-call
    # budget for the turn. A false negative here just falls through to the
    # existing router unchanged; see detect_feature_region_search's own
    # docstring for why a false positive is guarded against instead.
    fr_region, fr_feature_label, fr_feature_value = (
        _ask_api_module.detect_feature_region_search(req.question)
    )
    if fr_region or fr_feature_value:
        _ask_api_module.logger.info(
            "cpq_router: feature_region_search region=%r feature_label=%r "
            "feature_value=%r → search_products_combined",
            fr_region, fr_feature_label, fr_feature_value,
        )
        _route("feature_search", "FEATURE_REGION", mode,
               has_region=bool(fr_region), has_feature_value=bool(fr_feature_value))
        return _route_feature_region_search(
            req, reader, fr_region, fr_feature_label, fr_feature_value,
        )

    det_is_cpq = _ask_finish_cpq_result_module._deterministic_cpq_gate(req, reader)
    soft_quote = _ask_api_module.soft_quote_heuristic(req.question)
    raven_log("DEBUG", "P4", "ask.route.check feature_region=false gate and heuristic done", context={
        "check": "feature_region", "result": False, "det_is_cpq": det_is_cpq,
        "soft_quote": soft_quote, "policy_version": mode,
    })

    # ── deterministic_first: legacy short-circuit (no gateway LLM) ──────────
    if mode == "deterministic_first":
        is_cpq = (
            det_is_cpq
            or soft_quote
            or _llm_classify_is_cpq_question(req.question, req.workspace_id)
        )
        _route("quote" if is_cpq else "standard", "DETERMINISTIC_FIRST", mode,
               det_is_cpq=det_is_cpq, soft_quote=soft_quote)
        if is_cpq:
            return _route_quote(req, reader)
        return _ask_standard_pipeline_module._standard_ask_pipeline(req, reader)

    # ── llm_first / shadow: one top-level gateway call ──────────────────────
    route_meta = _ask_api_module.classify_ask_route(
        req.question,
        workspace_id=req.workspace_id,
        session_hint="none (cold start)",
        det_is_cpq=det_is_cpq,
        timeout_s=float(settings.cpq_intent_timeout_s or 120.0),
    )
    # N4: mid-session gateway in _run_cpq_turn will no-op this turn.
    _ask_api_module.mark_top_level_route_used()

    raven_log("DEBUG", "P4", "ask.route.classified gateway result", context={
        "llm_route": route_meta.route, "confidence": route_meta.confidence,
        "agreement": route_meta.agreement, "det_is_cpq": det_is_cpq,
        "soft_quote": soft_quote, "timed_out": bool(route_meta.timed_out),
        "has_error": bool(route_meta.error), "model_id": route_meta.model_id,
        "policy_version": mode,
    })
    if route_meta.error or route_meta.timed_out:
        return _handle_router_error(req, reader, route_meta, mode, det_is_cpq, soft_quote)

    # Bidirectional shadow log (LLM route + det auditor)
    log_fn = _ask_api_module.logger.warning if (
        mode == "shadow" and route_meta.agreement is False
    ) else _ask_api_module.logger.info
    # N5: shadow disagreements are WARNING-level so they show in ops filters.
    log_fn(
        "cpq_router_shadow: mode=%s llm_route=%s det_is_cpq=%s agreement=%s "
        "soft_quote=%s model_id=%s rationale=%r",
        mode, route_meta.route, det_is_cpq, route_meta.agreement,
        soft_quote, route_meta.model_id, route_meta.rationale,
    )

    if mode == "shadow":
        # Deterministic path still decides; gateway is observe-only.
        # N6: soft_quote widens det path so shadow traffic mirrors escape hatch.
        # docs/CPQ_QUANTITY_COUNTRY_SUMMARY_FIXES_2026_08_13.md turn-1
        # unified extraction plan: quantity/country stay observe-only here
        # too — "shadow" means the gateway's decision (including these two
        # new fields) must never silently change turn behavior, only be
        # logged. Strip them before the turn engine ever sees this
        # route_meta; the un-stripped original still goes to
        # _finish_cpq_result for logging via the closure below.
        _route("quote" if (det_is_cpq or soft_quote) else "standard", "SHADOW_DETERMINISTIC",
               mode, llm_route=route_meta.route, det_is_cpq=det_is_cpq,
               confidence=route_meta.confidence, agreement=route_meta.agreement)
        if det_is_cpq or soft_quote:
            _shadow_meta = dataclasses.replace(route_meta, quantity=None, country=None)
            return _route_quote(req, reader, _shadow_meta)
        return _ask_standard_pipeline_module._standard_ask_pipeline(req, reader)

    # ── llm_first: handlers execute the gateway decision ────────────────────
    _route(route_meta.route if route_meta.route in _ROADS else "standard", "LLM_ROUTE", mode,
           llm_route=route_meta.route, det_is_cpq=det_is_cpq, confidence=route_meta.confidence)
    if route_meta.route == "off_topic":
        return _ask_standard_pipeline_module._standard_ask_pipeline(req, reader)

    if route_meta.route == "quote":
        if det_is_cpq is False:
            _ask_api_module.logger.info(
                "cpq_router: llm_first quote with det_is_cpq=False "
                "(auditor disagreement — proceeding with LLM)",
            )
        return _route_quote(req, reader, route_meta)

    if route_meta.route == "attribute_search":
        # Attribute-first discovery; not grounded -> the quote path it took before.
        return _route_attribute_search(req, reader, route_meta) or _route_quote(
            req, reader, dataclasses.replace(route_meta, route="quote"))

    if route_meta.route == "qa":
        return _route_qa(req, reader, route_meta)

    if route_meta.route == "ambiguous":
        return _route_ambiguous(route_meta, req)

    return _ask_standard_pipeline_module._standard_ask_pipeline(req, reader)
