"""Regression pins for N1–N10 hardens (Andie Drama negative-case map)."""
from __future__ import annotations

import re
from unittest.mock import MagicMock, patch

from aryx.cpq.bom_gate import check_provenance
from aryx.cpq.engine import CpqEngine, _COUNTRY_PREP
from aryx.cpq.intent_gateway import (
    hard_off_topic,
    mark_top_level_route_used,
    soft_quote_heuristic,
    top_level_route_used,
    _cache_key,
    clear_gateway_cache,
)
from aryx.cpq.session_guard import (
    CLARIFY_STREAK_MAX,
    note_clarify,
    should_force_numbered_options,
    should_offer_guided_mode,
)
from aryx.cpq.state import ConfigAttr, CpqSession, MenuOption


# ── N1 country extraction ───────────────────────────────────────────────────

def test_n1_destination_country_is_united_states():
    m = _COUNTRY_PREP.search(
        "i want to order APX Next radios for destination country is United States"
    )
    assert m is not None
    assert "United States" in m.group(1)


def test_n1_destination_country_without_is():
    m = _COUNTRY_PREP.search(
        "order APX Next for destination country United States"
    )
    assert m is not None
    assert "United States" in m.group(1)


def test_n1_destination_country_as_united_states():
    """docs/config_consistency_issues_2026-07-30.md item 5: "...with
    destination country as United States" fell through every prior
    trigger — "as" sits between "destination country" and the real
    country name, so the country was silently dropped and re-asked
    despite being explicitly stated."""
    m = _COUNTRY_PREP.search(
        "I want to order APX Next radios 50 in qty for customer who is "
        "Houston City of with destination country as United States"
    )
    assert m is not None
    assert m.group(1) == "United States"


def test_n1_extract_hints_country():
    pytest = __import__("pytest")
    try:
        eng = CpqEngine()
    except Exception as exc:  # noqa: BLE001 — env without psycopg
        pytest.skip(f"CpqEngine import unavailable: {exc}")
    hints = eng.extract_hints(
        "order APX Next radios for destination country United States"
    )
    assert hints.get("country")
    assert "united" in hints["country"].lower() or hints["country"] in (
        "United States", "US", "Usa",
    )


# ── N6 soft quote / N10 hard off-topic ───────────────────────────────────────

def test_n6_soft_quote_order_apx():
    assert soft_quote_heuristic("I want to order APX Next radios 50 qty")


def test_n6_soft_quote_not_weather():
    assert not soft_quote_heuristic("what's the weather in Houston")


def test_n10_hard_off_topic_astrology():
    assert hard_off_topic("astra in astrological sense")
    assert hard_off_topic("tell me a joke")
    assert not hard_off_topic("order APX Next for United States")


# ── N4 one LLM call contextvar ───────────────────────────────────────────────

def test_n4_top_level_route_marks_contextvar():
    # ContextVar default false; mark then true
    # Note: may be dirty from prior tests in same process — set explicitly
    from aryx.cpq import intent_gateway as gw
    token = gw._top_level_route_used.set(False)
    try:
        assert top_level_route_used() is False
        mark_top_level_route_used()
        assert top_level_route_used() is True
    finally:
        gw._top_level_route_used.reset(token)


# ── N7 provenance ───────────────────────────────────────────────────────────

def test_n7_catalog_option_always_ok():
    attr = ConfigAttr(
        entity_id=1, variable_name="hW", display_label="HW",
        required=False, default_value="",
        options=[MenuOption("H45", "APX NEXT")],
    )
    s = CpqSession()
    s.filled = {"hW": "H45"}
    s.filled_source = {"hW": "cascade"}
    s.display_filled = {"hW": "APX NEXT"}
    assert check_provenance([attr], s) == []


def test_n7_cascade_free_text_ok():
    attr = ConfigAttr(
        entity_id=1, variable_name="note", display_label="Note",
        required=False, default_value="", options=[],
    )
    s = CpqSession()
    s.filled = {"note": "some free text"}
    s.filled_source = {"note": "cascade"}
    s.display_filled = {"note": "some free text"}
    assert check_provenance([attr], s) == []


def test_n7_still_rejects_invented_menu_value():
    attr = ConfigAttr(
        entity_id=1, variable_name="hW", display_label="HW",
        required=False, default_value="",
        options=[MenuOption("H45", "APX NEXT")],
    )
    s = CpqSession()
    s.filled = {"hW": "HALLUCINATED"}
    s.filled_source = {"hW": "auto"}
    s.display_filled = {"hW": "HALLUCINATED"}
    assert check_provenance([attr], s)


# ── N8 clarify loops ────────────────────────────────────────────────────────

def test_n8_numbered_options_after_two_clarifies():
    s = CpqSession()
    note_clarify(s, "hW")
    note_clarify(s, "hW")
    assert should_force_numbered_options(s, "hW")


def test_n8_guided_after_five_unresolved():
    s = CpqSession()
    for _ in range(5):
        note_clarify(s, None)
    assert should_offer_guided_mode(s)


# ── N9 cache isolation ───────────────────────────────────────────────────────

def test_n9_cache_key_includes_model_and_pid():
    s = CpqSession()
    s.filled = {"a": "1"}
    k1 = _cache_key("change hardware", s, "gemini-2.5-pro")
    k2 = _cache_key("change hardware", s, "other-model")
    assert k1 != k2
    assert "gemini-2.5-pro" in k1
    assert "pid=" in k1


# ── N5 shadow disagreement logging path exists in run_ask ───────────────────

def test_n5_run_ask_shadow_disagreement_uses_warning(caplog):
    import logging
    from aryx.api.ask_api import AskRequest, run_ask
    from aryx.cpq.intent_gateway import AskRouteDecision

    req = AskRequest(
        question="random unrelated chatter",
        workspace_id=1, history=[], session_data={},
    )
    meta = AskRouteDecision(
        route="quote", confidence="high",
        clarifying_question=None, rationale="disagree",
        model_id="m", det_is_cpq=False, agreement=False,
    )
    with patch("aryx.api.ask_api._reader", return_value=object()), \
         patch("aryx.api.ask_api.get_settings") as gs, \
         patch("aryx.api.ask_api.classify_ask_route", return_value=meta), \
         patch("aryx.api.ask_api._deterministic_cpq_gate", return_value=False), \
         patch("aryx.api.ask_api.hard_off_topic", return_value=False), \
         patch("aryx.api.ask_api.soft_quote_heuristic", return_value=False), \
         patch("aryx.api.ask_api._standard_ask_pipeline",
               return_value={"answer": "std", "tools_called": [], "usage": {}}), \
         patch("aryx.api.ask_api.mark_top_level_route_used"):
        gs.return_value.cpq_intent_mode = "shadow"
        gs.return_value.cpq_intent_timeout_s = 10.0
        with caplog.at_level(logging.WARNING):
            run_ask(req)
    assert any("cpq_router_shadow" in r.message for r in caplog.records)


# ── N2 cold QA does not set product on empty session ─────────────────────────

def test_n2_route_qa_read_only_product():
    from aryx.api.ask_api import AskRequest, _route_qa

    req = AskRequest(
        question="what are the options for product",
        workspace_id=1, history=[], session_data={},
    )
    with patch("aryx.api.ask_api._cpq_engine") as eng, \
         patch("aryx.api.ask_api._handle_cpq_qa") as mock_qa, \
         patch("aryx.api.ask_api._attach_share_flags", side_effect=lambda r, *a, **k: r), \
         patch("aryx.api.ask_api.set_run_id"):
        eng.extract_hints.return_value = {}
        eng.detect_product_mention.return_value = "aSTRO25_bom"
        eng.load_product_config.return_value = ([], "aSTRO25_bom")
        mock_qa.return_value = {
            "answer": "options…",
            "session_data": {"mode": "cpq", "product_name": ""},
            "tools_called": ["cpq_qa()"],
            "usage": {},
        }
        out = _route_qa(req, object())
        # load called for context, but detect was read-only
        eng.detect_product_mention.assert_called()
        eng.load_product_config.assert_called()
        # session passed to qa should not have product forced by our shell
        sess_arg = mock_qa.call_args[0][1]
        assert sess_arg.product_name == ""


# ── N6 escape hatch soft quote ───────────────────────────────────────────────

def test_n6_escape_hatch_soft_quote_routes_cpq():
    from aryx.api.ask_api import AskRequest, run_ask
    from aryx.cpq.intent_gateway import AskRouteDecision

    req = AskRequest(
        question="I want to order APX Next radios for destination country United States",
        workspace_id=1, history=[], session_data={},
    )
    meta = AskRouteDecision(
        route="quote", confidence="low",
        clarifying_question=None, rationale="timeout",
        timed_out=True, error="timeout", model_id="m", det_is_cpq=False,
    )
    with patch("aryx.api.ask_api._reader", return_value=object()), \
         patch("aryx.api.ask_api.get_settings") as gs, \
         patch("aryx.api.ask_api.classify_ask_route", return_value=meta), \
         patch("aryx.api.ask_api._deterministic_cpq_gate", return_value=False), \
         patch("aryx.api.ask_api.hard_off_topic", return_value=False), \
         patch("aryx.api.ask_api._run_cpq_turn") as mock_cpq, \
         patch("aryx.api.ask_api._attach_share_flags", side_effect=lambda r, *a, **k: r), \
         patch("aryx.api.ask_api.mark_top_level_route_used"), \
         patch("aryx.api.ask_api._standard_ask_pipeline") as mock_std:
        gs.return_value.cpq_intent_mode = "llm_first"
        gs.return_value.cpq_intent_timeout_s = 10.0
        mock_cpq.return_value = {
            "answer": "cpq via soft quote", "tools_called": [],
            "session_data": {}, "usage": {},
        }
        out = run_ask(req)
    mock_cpq.assert_called_once()
    mock_std.assert_not_called()
    assert out["answer"] == "cpq via soft quote"
