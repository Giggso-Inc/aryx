"""_apply_real_llm_usage / _run_cpq_turn's usage-reporting wrap point —
docs/CPQ_Usage_Reporting_Gap issues #1/#2: a CPQ turn response that took a
deterministic path must have its hardcoded "cpq-engine, 0 tokens"
placeholder replaced with the real accumulated LLM usage whenever
llm_runtime recorded any actual call during the turn, regardless of which
of the many internal response-construction blocks built the response.
"""
from __future__ import annotations

from unittest.mock import patch

import aryx.api.ask_api as api
from aryx import llm_runtime


def test_noop_when_no_usage_key():
    result = {"answer": "no usage field at all"}
    api._apply_real_llm_usage(result)
    assert result == {"answer": "no usage field at all"}


def test_noop_when_turn_usage_never_reset():
    with patch("aryx.api.ask_api.llm_runtime.get_turn_usage", lambda: None):
        result = {"answer": "...", "usage": {
            "prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
            "menial_model": "cpq-engine", "answer_model": "cpq-engine",
        }}
        api._apply_real_llm_usage(result)
        assert result["usage"]["menial_model"] == "cpq-engine"
        assert result["usage"]["prompt_tokens"] == 0


def test_noop_when_zero_calls_recorded():
    fake = {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
            "calls": 0, "models": []}
    with patch("aryx.api.ask_api.llm_runtime.get_turn_usage", lambda: fake):
        result = {"answer": "...", "usage": {
            "prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
            "menial_model": "cpq-engine", "answer_model": "cpq-engine",
        }}
        api._apply_real_llm_usage(result)
        assert result["usage"]["menial_model"] == "cpq-engine"


def test_replaces_hardcoded_placeholder_with_real_usage():
    fake = {"prompt_tokens": 150, "completion_tokens": 20, "latency_ms": 340,
            "calls": 2, "models": ["gemini-3.1-pro-preview"]}
    with patch("aryx.api.ask_api.llm_runtime.get_turn_usage", lambda: fake):
        result = {"answer": "...", "usage": {
            "prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
            "menial_model": "cpq-engine", "answer_model": "cpq-engine",
        }}
        api._apply_real_llm_usage(result)
    assert result["usage"] == {
        "prompt_tokens": 150, "completion_tokens": 20, "latency_ms": 340,
        "menial_model": "gemini-3.1-pro-preview",
        "answer_model": "gemini-3.1-pro-preview",
    }


def test_multiple_distinct_models_are_joined():
    fake = {"prompt_tokens": 50, "completion_tokens": 5, "latency_ms": 100,
            "calls": 2, "models": ["gemini-2.5-flash", "gemini-3.1-pro-preview"]}
    with patch("aryx.api.ask_api.llm_runtime.get_turn_usage", lambda: fake):
        result = {"answer": "...", "usage": {
            "prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
            "menial_model": "cpq-engine", "answer_model": "cpq-engine",
        }}
        api._apply_real_llm_usage(result)
    assert result["usage"]["menial_model"] == "gemini-2.5-flash, gemini-3.1-pro-preview"


def test_run_cpq_turn_end_to_end_resets_and_reports(monkeypatch):
    """Integration-level: _run_cpq_turn itself resets the accumulator and
    applies real usage to whatever _run_cpq_turn_inner returns, without
    needing to touch _run_cpq_turn_inner's own internals at all."""
    def _fake_inner(req, reader, route_meta=None):
        # Simulate a real LLM call happening somewhere deep inside this
        # turn (BML Tier-2, an intent classifier, anything) via the same
        # llm_runtime.chat() choke point every real call site uses.
        with patch("aryx.llm_runtime.complete_text",
                   lambda *a, **k: ("reply", 30, 4)), \
             patch.object(llm_runtime, "_log_call", lambda *a, **k: None):
            llm_runtime.chat("answer", "sys", "user")
        return {"answer": "...", "session_data": {}, "usage": {
            "prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
            "menial_model": "cpq-engine", "answer_model": "cpq-engine",
        }}

    monkeypatch.setattr(api, "_run_cpq_turn_inner", _fake_inner)
    monkeypatch.setattr(api, "enforce_conversational_invariant", lambda r: r)

    req = api.AskRequest(question="anything", workspace_id=1, session_data={})
    result = api._run_cpq_turn(req, reader=None)

    assert result["usage"]["prompt_tokens"] == 30
    assert result["usage"]["completion_tokens"] == 4
    assert result["usage"]["menial_model"] != "cpq-engine"
