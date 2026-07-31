"""Few-shot routing contract — owner positive + negative cases (Prompt 3).

Tests the top-level ask-route classifier schema/parse and the run_ask
mode switch without requiring a live LLM. Few-shot strings from the
owner must remain embedded in the gateway prompt (string pins).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from aryx.cpq.intent_gateway import (
    _ROUTE_FEW_SHOTS,
    AskRouteDecision,
    _parse_route,
    classify_ask_route,
    map_route_to_det_expectation,
)


# ── Prompt must retain owner few-shots ──────────────────────────────────────

def test_few_shot_prompt_contains_positive_order_apx():
    assert "APX Next radios" in _ROUTE_FEW_SHOTS
    assert "destination country is United States" in _ROUTE_FEW_SHOTS
    assert "route=quote" in _ROUTE_FEW_SHOTS


def test_few_shot_prompt_contains_positive_change_hardware():
    assert "change the hardware version" in _ROUTE_FEW_SHOTS


def test_few_shot_prompt_contains_positive_astrology_off_topic():
    assert "astra in astrological sense" in _ROUTE_FEW_SHOTS
    assert "route=off_topic" in _ROUTE_FEW_SHOTS


def test_few_shot_prompt_contains_negative_country_reask():
    # N1: must NOT re-ask country when already stated
    assert "destination country United States" in _ROUTE_FEW_SHOTS
    assert "what's the destination country" in _ROUTE_FEW_SHOTS or (
        "destination country" in _ROUTE_FEW_SHOTS and "WRONG" in _ROUTE_FEW_SHOTS
    )


def test_few_shot_prompt_contains_negative_options_for_product():
    # N2: options question is QA, not silent product switch
    assert "what are the options for product" in _ROUTE_FEW_SHOTS
    assert "route=qa" in _ROUTE_FEW_SHOTS
    assert "softwareSolutions_BOM" in _ROUTE_FEW_SHOTS


def test_few_shot_prompt_contains_negative_mid_session_switch():
    # N3: mid-session family hop must go through CPQ switch confirm
    assert "CommandCentral Aware" in _ROUTE_FEW_SHOTS
    assert "aSTRO25_bom" in _ROUTE_FEW_SHOTS


# ── Parse / quarantine ──────────────────────────────────────────────────────

def test_parse_quote_route():
    d = _parse_route({
        "route": "quote", "confidence": "high",
        "clarifying_question": None,
        "rationale": "full order with country",
    })
    assert d is not None
    assert d.route == "quote"


def test_parse_off_topic_astrology():
    d = _parse_route({
        "route": "off_topic", "confidence": "high",
        "clarifying_question": None,
        "rationale": "astrology",
    })
    assert d is not None and d.route == "off_topic"


def test_parse_qa_options_for_product():
    d = _parse_route({
        "route": "qa", "confidence": "high",
        "clarifying_question": None,
        "rationale": "options question",
    })
    assert d is not None and d.route == "qa"


def test_low_confidence_quote_downgrades_to_ambiguous():
    d = _parse_route({
        "route": "quote", "confidence": "low",
        "clarifying_question": None,
        "rationale": "unsure",
    })
    assert d is not None and d.route == "ambiguous"
    assert d.clarifying_question


def test_map_route_det_expectation():
    assert map_route_to_det_expectation("quote") is True
    assert map_route_to_det_expectation("off_topic") is False
    assert map_route_to_det_expectation("qa") is False


# ── classify_ask_route with mocked LLM ──────────────────────────────────────

def test_classify_order_apx_returns_quote():
    raw = (
        '{"route":"quote","confidence":"high","clarifying_question":null,'
        '"rationale":"full order APX with US destination"}'
    )
    with patch(
        "aryx.cpq.intent_gateway._pinned_chat",
        return_value=(raw, 5, 3),
    ):
        d = classify_ask_route(
            "I want to order APX Next radios 50 qty for customer City of Houston "
            "whose destination country is United States",
            det_is_cpq=True,
        )
    assert d.route == "quote"
    assert not d.error
    assert d.agreement is True


def test_classify_astrology_off_topic():
    raw = (
        '{"route":"off_topic","confidence":"high","clarifying_question":null,'
        '"rationale":"astrology not product config"}'
    )
    with patch(
        "aryx.cpq.intent_gateway._pinned_chat",
        return_value=(raw, 5, 3),
    ):
        d = classify_ask_route(
            "astra in astrological sense",
            det_is_cpq=False,
        )
    assert d.route == "off_topic"
    assert d.agreement is True


def test_classify_options_for_product_is_qa_not_quote():
    raw = (
        '{"route":"qa","confidence":"high","clarifying_question":null,'
        '"rationale":"options question not family switch"}'
    )
    with patch(
        "aryx.cpq.intent_gateway._pinned_chat",
        return_value=(raw, 5, 3),
    ):
        d = classify_ask_route(
            "what are the options for product",
            det_is_cpq=False,
        )
    assert d.route == "qa"


def test_timeout_escape_hatch():
    import concurrent.futures

    def _hang(*_a, **_k):
        raise concurrent.futures.TimeoutError()

    # Force ThreadPoolExecutor.result to raise TimeoutError by patching
    with patch(
        "aryx.cpq.intent_gateway._pinned_chat",
        side_effect=lambda *a, **k: (_ for _ in ()).throw(
            concurrent.futures.TimeoutError()
        ),
    ):
        # Actually timeout is from fut.result — patch concurrent futures
        class _Fut:
            def result(self, timeout=None):
                raise concurrent.futures.TimeoutError()

        class _Pool:
            def __init__(self, *a, **k): pass
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def submit(self, fn): return _Fut()

        with patch("concurrent.futures.ThreadPoolExecutor", _Pool):
            d = classify_ask_route("order APX Next", det_is_cpq=True, timeout_s=0.01)
    assert d.timed_out or d.error


# ── run_ask mode matrix ─────────────────────────────────────────────────────

def test_run_ask_live_session_skips_top_level_gateway():
    from aryx.api.ask_api import AskRequest, run_ask

    req = AskRequest(
        question="change the hardware version",
        workspace_id=1,
        history=[],
        session_data={"mode": "cpq", "product_name": "aSTRO25_bom", "status": "configuring"},
    )
    with patch("aryx.api.ask_api._reader", return_value=object()), \
         patch("aryx.api.ask_api.classify_ask_route") as mock_route, \
         patch("aryx.api.ask_api._run_cpq_turn") as mock_cpq, \
         patch("aryx.api.ask_api._attach_share_flags", side_effect=lambda r, *a, **k: r), \
         patch("aryx.api.ask_api._validate_workspace"):
        mock_cpq.return_value = {
            "answer": "Which value would you like for Hardware Version?",
            "tools_called": ["cpq_change_target_no_value()"],
            "session_data": req.session_data,
            "usage": {},
        }
        out = run_ask(req)
    mock_route.assert_not_called()
    mock_cpq.assert_called_once()
    assert "Hardware Version" in out["answer"] or "hardware" in out["answer"].lower()


def test_run_ask_llm_first_off_topic_goes_standard():
    from aryx.api.ask_api import AskRequest, run_ask

    req = AskRequest(
        question="astra in astrological sense",
        workspace_id=1, history=[], session_data={},
    )
    meta = AskRouteDecision(
        route="off_topic", confidence="high",
        clarifying_question=None, rationale="astrology",
        model_id="gemini-2.5-pro", det_is_cpq=False, agreement=True,
    )
    with patch("aryx.api.ask_api._reader", return_value=object()), \
         patch("aryx.api.ask_api.get_settings") as gs, \
         patch("aryx.api.ask_api.classify_ask_route", return_value=meta), \
         patch("aryx.api.ask_api._deterministic_cpq_gate", return_value=False), \
         patch("aryx.api.ask_api._standard_ask_pipeline") as mock_std, \
         patch("aryx.api.ask_api._run_cpq_turn") as mock_cpq:
        gs.return_value.cpq_intent_mode = "llm_first"
        gs.return_value.cpq_intent_timeout_s = 10.0
        mock_std.return_value = {
            "answer": "Astrology is outside of what I track...",
            "tools_called": [], "usage": {},
        }
        out = run_ask(req)
    mock_cpq.assert_not_called()
    mock_std.assert_called_once()
    assert "Astrology" in out["answer"] or "outside" in out["answer"].lower()


def test_run_ask_llm_first_quote_uses_cpq_turn():
    from aryx.api.ask_api import AskRequest, run_ask

    req = AskRequest(
        question=(
            "I want to order APX Next radios 50 qty for customer City of Houston "
            "whose destination country is United States"
        ),
        workspace_id=1, history=[], session_data={},
    )
    meta = AskRouteDecision(
        route="quote", confidence="high",
        clarifying_question=None, rationale="full order",
        model_id="gemini-2.5-pro", det_is_cpq=True, agreement=True,
    )
    with patch("aryx.api.ask_api._reader", return_value=object()), \
         patch("aryx.api.ask_api.get_settings") as gs, \
         patch("aryx.api.ask_api.classify_ask_route", return_value=meta), \
         patch("aryx.api.ask_api._deterministic_cpq_gate", return_value=True), \
         patch("aryx.api.ask_api._run_cpq_turn") as mock_cpq, \
         patch("aryx.api.ask_api._attach_share_flags", side_effect=lambda r, *a, **k: r):
        gs.return_value.cpq_intent_mode = "llm_first"
        gs.return_value.cpq_intent_timeout_s = 10.0
        mock_cpq.return_value = {
            "answer": "Configuration complete for **aSTRO25_bom**.",
            "tools_called": ["cpq_complete()"],
            "session_data": {"mode": "cpq", "status": "awaiting_approval"},
            "usage": {},
        }
        out = run_ask(req)
    mock_cpq.assert_called_once()
    assert "aSTRO25_bom" in out["answer"] or "Configuration complete" in out["answer"]


def test_run_ask_shadow_follows_deterministic_not_llm():
    """Shadow: LLM says off_topic but det says CPQ → still CPQ (det wins)."""
    from aryx.api.ask_api import AskRequest, run_ask

    req = AskRequest(
        question="order APX Next for United States",
        workspace_id=1, history=[], session_data={},
    )
    meta = AskRouteDecision(
        route="off_topic", confidence="high",
        clarifying_question=None, rationale="wrong",
        model_id="m", det_is_cpq=True, agreement=False,
    )
    with patch("aryx.api.ask_api._reader", return_value=object()), \
         patch("aryx.api.ask_api.get_settings") as gs, \
         patch("aryx.api.ask_api.classify_ask_route", return_value=meta), \
         patch("aryx.api.ask_api._deterministic_cpq_gate", return_value=True), \
         patch("aryx.api.ask_api._run_cpq_turn") as mock_cpq, \
         patch("aryx.api.ask_api._attach_share_flags", side_effect=lambda r, *a, **k: r), \
         patch("aryx.api.ask_api._standard_ask_pipeline") as mock_std:
        gs.return_value.cpq_intent_mode = "shadow"
        gs.return_value.cpq_intent_timeout_s = 10.0
        mock_cpq.return_value = {
            "answer": "cpq path", "tools_called": [],
            "session_data": {"mode": "cpq"}, "usage": {},
        }
        out = run_ask(req)
    mock_cpq.assert_called_once()
    mock_std.assert_not_called()
    assert out["answer"] == "cpq path"


def test_run_ask_escape_hatch_on_gateway_error():
    from aryx.api.ask_api import AskRequest, run_ask

    req = AskRequest(
        question="order APX Next",
        workspace_id=1, history=[], session_data={},
    )
    meta = AskRouteDecision(
        route="quote", confidence="low",
        clarifying_question=None, rationale="timeout",
        timed_out=True, error="timeout", model_id="m", det_is_cpq=True,
    )
    with patch("aryx.api.ask_api._reader", return_value=object()), \
         patch("aryx.api.ask_api.get_settings") as gs, \
         patch("aryx.api.ask_api.classify_ask_route", return_value=meta), \
         patch("aryx.api.ask_api._deterministic_cpq_gate", return_value=True), \
         patch("aryx.api.ask_api._run_cpq_turn") as mock_cpq, \
         patch("aryx.api.ask_api._attach_share_flags", side_effect=lambda r, *a, **k: r):
        gs.return_value.cpq_intent_mode = "llm_first"
        gs.return_value.cpq_intent_timeout_s = 10.0
        mock_cpq.return_value = {
            "answer": "escaped to det", "tools_called": [],
            "session_data": {}, "usage": {},
        }
        out = run_ask(req)
    mock_cpq.assert_called_once()
    assert out["answer"] == "escaped to det"
