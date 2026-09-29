"""CPQ_Hardcode_Audit_dev_oci_2026-09-25.md T8: shadow-log-only
measurement phase for the hard off-topic veto -- never changes real
routing, only observes (when cpq_off_topic_veto_shadow_enabled) what a
strong/weak term split would have decided, so the audit's proposed
"never override a confident quote/qa on a weak term" policy can be
validated against real traffic before it's ever shipped as a real
behavior change.
"""
from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

from aryx.cpq.intent_gateway.intent_gateway import (
    _off_topic_shadow_term_strength,
    classify_ask_route,
)


def _shadow_settings(enabled: bool):
    mock_cfg = MagicMock()
    mock_cfg.return_value.cpq_off_topic_veto_shadow_enabled = enabled
    mock_cfg.return_value.cpq_intent_gemini_model = "test-model"
    mock_cfg.return_value.cpq_intent_timeout_s = 5.0
    return patch("aryx.cpq.intent_gateway.intent_gateway.get_settings", mock_cfg)


def test_term_strength_weather_is_weak():
    assert _off_topic_shadow_term_strength("what's the weather like today?") == "weak"


def test_term_strength_world_cup_is_weak():
    assert _off_topic_shadow_term_strength("who won the world cup?") == "weak"


def test_term_strength_astrology_is_strong():
    assert _off_topic_shadow_term_strength("what's my horoscope say?") == "strong"


def test_term_strength_no_match_is_none():
    assert _off_topic_shadow_term_strength("I want to order 50 APX Next radios") is None


def test_pre_llm_veto_shadow_off_logs_nothing(caplog):
    with (
        _shadow_settings(False),
        caplog.at_level(logging.INFO, logger="aryx.cpq.intent_gateway.intent_gateway"),
    ):
        d = classify_ask_route("what's the weather like?", det_is_cpq=False)
    assert d.route == "off_topic"
    assert not any("cpq_off_topic_veto_shadow" in r.message for r in caplog.records)


def test_pre_llm_veto_shadow_on_logs_term_strength_without_changing_routing(caplog):
    with (
        _shadow_settings(True),
        caplog.at_level(logging.INFO, logger="aryx.cpq.intent_gateway.intent_gateway"),
    ):
        d = classify_ask_route("what's the weather like?", det_is_cpq=False)
    assert d.route == "off_topic"  # unchanged real routing
    shadow_logs = [r.message for r in caplog.records if "cpq_off_topic_veto_shadow" in r.message]
    assert len(shadow_logs) == 1
    assert "term_strength=weak" in shadow_logs[0]
    assert "site=pre_llm" in shadow_logs[0]


def test_post_llm_site_is_unreachable_dead_code(caplog):
    """CPQ_Hardcode_Audit_dev_oci_2026-09-25.md T8 discovery: the pre-LLM
    veto above always returns first whenever hard_off_topic(question) is
    true (same unmodified `question`), so the "N10 post-LLM" override
    block can never execute -- confirmed here by asserting the run never
    reaches an LLM call (_pinned_chat) at all for a message that matches
    an off-topic term, even though the post-LLM block still exists in
    the code."""
    with (
        _shadow_settings(True),
        patch(
            "aryx.cpq.intent_gateway.intent_gateway._pinned_chat",
            side_effect=AssertionError("LLM should never be called -- pre-LLM veto already returned"),
        ),
    ):
        d = classify_ask_route("tell me my horoscope for today", det_is_cpq=True)
    assert d.route == "off_topic"
    assert d.rationale == "hard_off_topic_veto"  # the pre-LLM rationale, not the post-LLM one
