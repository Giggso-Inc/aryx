"""Attribute-first discovery, phase 1: the `attribute_search` route.

A cold-start message that starts from an attribute instead of a product
("I want a product that has ATT as a carrier") is routed to
`attribute_search` by classify_ask_route, carrying the raw attribute label
and optional value. Gated by ARYX_CPQ_ATTR_SEARCH_ENABLED (off by default):
with the flag off, the router's prompt/schema/parsing are byte-identical to
before. When the attribute can't be grounded, run_ask falls back to today's
quote path (the phase 2 handler is covered in test_cpq_attribute_search_handler.py).
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from aryx.cpq.intent_gateway.intent_gateway import (
    _ROUTE_SCHEMA,
    _parse_route,
    classify_ask_route,
    map_route_to_det_expectation,
)

_GW = "aryx.cpq.intent_gateway.intent_gateway"


def _settings(enabled: object):
    mock_cfg = MagicMock()
    mock_cfg.return_value.cpq_attr_search_enabled = enabled
    mock_cfg.return_value.cpq_off_topic_veto_shadow_enabled = False
    mock_cfg.return_value.cpq_intent_gemini_model = "test-model"
    mock_cfg.return_value.cpq_intent_timeout_s = 5.0
    return patch(f"{_GW}.get_settings", mock_cfg)


def _llm_reply(payload: dict):
    return patch(f"{_GW}._pinned_chat", return_value=(json.dumps(payload), 10, 5))


# ── _parse_route ─────────────────────────────────────────────────────────────


def test_parse_rejects_attribute_search_when_not_allowed():
    raw = {"route": "attribute_search", "confidence": "high",
           "clarifying_question": None, "rationale": "", "attribute_label": "carrier"}
    assert _parse_route(raw) is None


def test_parse_extracts_label_and_value():
    d = _parse_route({
        "route": "attribute_search", "confidence": "high",
        "clarifying_question": None, "rationale": "attr first",
        "attribute_label": " carrier ", "attribute_value": " ATT ",
    }, allow_attribute_search=True)
    assert d.route == "attribute_search"
    assert d.attribute_label == "carrier"
    assert d.attribute_value == "ATT"


def test_parse_label_only_keeps_value_none():
    d = _parse_route({
        "route": "attribute_search", "confidence": "high",
        "clarifying_question": None, "rationale": "",
        "attribute_label": "carrier selection", "attribute_value": None,
    }, allow_attribute_search=True)
    assert d.route == "attribute_search"
    assert d.attribute_label == "carrier selection"
    assert d.attribute_value is None


def test_parse_attribute_search_without_label_downgrades_to_quote():
    d = _parse_route({
        "route": "attribute_search", "confidence": "high",
        "clarifying_question": None, "rationale": "",
        "attribute_label": "  ", "attribute_value": "ATT",
    }, allow_attribute_search=True)
    assert d.route == "quote"
    assert d.attribute_label is None
    assert "attribute_search_missing_label" in d.rationale


def test_parse_low_confidence_attribute_search_becomes_ambiguous():
    d = _parse_route({
        "route": "attribute_search", "confidence": "low",
        "clarifying_question": None, "rationale": "",
        "attribute_label": "carrier", "attribute_value": "ATT",
    }, allow_attribute_search=True)
    assert d.route == "ambiguous"
    assert d.clarifying_question


def test_parse_non_string_attribute_fields_fail_closed_to_none():
    d = _parse_route({
        "route": "attribute_search", "confidence": "high",
        "clarifying_question": None, "rationale": "",
        "attribute_label": "carrier", "attribute_value": 42,
    }, allow_attribute_search=True)
    assert d.attribute_value is None


def test_parse_keeps_quantity_and_country_on_attribute_search():
    d = _parse_route({
        "route": "attribute_search", "confidence": "high",
        "clarifying_question": None, "rationale": "",
        "attribute_label": "carrier", "attribute_value": "ATT",
        "quantity": 5, "country": "Germany",
    }, allow_attribute_search=True)
    assert d.quantity == 5
    assert d.country == "Germany"


def test_parse_quote_route_has_no_attribute_fields():
    d = _parse_route({
        "route": "quote", "confidence": "high", "clarifying_question": None,
        "rationale": "", "attribute_label": "carrier", "attribute_value": "ATT",
    }, allow_attribute_search=True)
    assert d.route == "quote"
    assert d.attribute_label is None
    assert d.attribute_value is None


# ── classify_ask_route ───────────────────────────────────────────────────────


def test_flag_off_prompt_and_schema_unchanged():
    assert "attribute_search" not in _ROUTE_SCHEMA["properties"]["route"]["enum"]
    with _settings(False), _llm_reply({
        "route": "quote", "confidence": "high", "clarifying_question": None, "rationale": "",
    }) as chat:
        classify_ask_route("I want a product that has ATT as a carrier")
    sys_prompt = chat.call_args[0][0]
    assert "attribute_search" not in sys_prompt


def test_flag_must_be_exactly_true():
    """A MagicMock settings object (as many tests use) must not switch it on."""
    with _settings(MagicMock()), _llm_reply({
        "route": "quote", "confidence": "high", "clarifying_question": None, "rationale": "",
    }) as chat:
        classify_ask_route("I want a product that has ATT as a carrier")
    assert "attribute_search" not in chat.call_args[0][0]


def test_flag_off_attribute_search_reply_is_treated_as_invalid():
    with _settings(False), _llm_reply({
        "route": "attribute_search", "confidence": "high", "clarifying_question": None,
        "rationale": "", "attribute_label": "carrier", "attribute_value": "ATT",
    }):
        d = classify_ask_route("I want a product that has ATT as a carrier")
    assert d.route != "attribute_search"
    assert d.error == "double_validation_failure"


def test_flag_on_prompt_offers_attribute_search():
    with _settings(True), _llm_reply({
        "route": "quote", "confidence": "high", "clarifying_question": None, "rationale": "",
    }) as chat:
        classify_ask_route("hello")
    sys_prompt = chat.call_args[0][0]
    assert "attribute_search" in sys_prompt
    assert "attribute_label" in sys_prompt


def test_flag_on_value_example_routes_to_attribute_search():
    with _settings(True), _llm_reply({
        "route": "attribute_search", "confidence": "high", "clarifying_question": None,
        "rationale": "attribute first", "attribute_label": "carrier", "attribute_value": "ATT",
    }):
        d = classify_ask_route("I want a product that has ATT as a carrier")
    assert d.route == "attribute_search"
    assert (d.attribute_label, d.attribute_value) == ("carrier", "ATT")
    assert d.error == ""


def test_flag_on_label_only_example_routes_to_attribute_search():
    with _settings(True), _llm_reply({
        "route": "attribute_search", "confidence": "high", "clarifying_question": None,
        "rationale": "attribute first", "attribute_label": "carrier selection",
        "attribute_value": None,
    }):
        d = classify_ask_route("Which products are available for carrier selection")
    assert d.route == "attribute_search"
    assert d.attribute_value is None


def test_attribute_search_counts_as_cpq_for_auditor_agreement():
    assert map_route_to_det_expectation("attribute_search") is True
    with _settings(True), _llm_reply({
        "route": "attribute_search", "confidence": "high", "clarifying_question": None,
        "rationale": "", "attribute_label": "carrier", "attribute_value": "ATT",
    }):
        d = classify_ask_route("product with ATT as carrier", det_is_cpq=True)
    assert d.agreement is True


# ── run_ask dispatch (ungrounded fallback) ──────────────────────────────────────


def test_run_ask_ungrounded_attribute_search_falls_back_to_quote_path():
    from aryx.api.ask_run_ask import run_ask
    from aryx.cpq.intent_gateway.intent_gateway import AskRouteDecision

    meta = AskRouteDecision(
        route="attribute_search", confidence="high", clarifying_question=None,
        rationale="", attribute_label="carrier", attribute_value="ATT",
        quantity=5, country="Germany",
    )
    req = MagicMock(question="I want a product that has ATT as a carrier",
                    workspace_id=1, session_data={})
    cfg = MagicMock(cpq_intent_mode="llm_first", cpq_intent_timeout_s=5.0)
    with patch("aryx.api.ask_api.get_settings", return_value=cfg), \
         patch("aryx.api.ask_api.hard_off_topic", return_value=False), \
         patch("aryx.api.ask_api.detect_feature_region_search", return_value=(None, None, None)), \
         patch("aryx.api.ask_api.soft_quote_heuristic", return_value=False), \
         patch("aryx.api.ask_api.classify_ask_route", return_value=meta), \
         patch("aryx.api.ask_api.mark_top_level_route_used"), \
         patch("aryx.api.ask_core_helpers._reader", return_value=MagicMock()), \
         patch("aryx.api.ask_response_building.ask_finish_cpq_result._deterministic_cpq_gate",
               return_value=True), \
         patch("aryx.api.ask_run_ask._route_attribute_search", return_value=None), \
         patch("aryx.api.ask_run_ask._route_quote", return_value={"answer": "q"}) as route_quote:
        out = run_ask(req)
    assert out == {"answer": "q"}
    passed_meta = route_quote.call_args[0][2]
    assert passed_meta.route == "quote"
    assert (passed_meta.quantity, passed_meta.country) == (5, "Germany")
