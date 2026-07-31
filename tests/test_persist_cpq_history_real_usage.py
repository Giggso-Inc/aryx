"""_persist_cpq_history — docs/CPQ_Usage_Reporting_Gap follow-up: the ~50
call sites scattered through _run_cpq_turn_inner that persist a CPQ turn to
aryx_ask_history all funnel through this one helper, which used to hardcode
{"cpq-engine", 0 tokens} unconditionally — even when a real LLM call had
already happened earlier in the same turn (_run_cpq_turn's response usage
was fixed for the live response, but the DB row stayed fake). Fixed by
having the helper read the same llm_runtime.get_turn_usage() ContextVar
_apply_real_llm_usage already uses.
"""
from __future__ import annotations

from unittest.mock import patch

import aryx.api.ask_api as api


def test_default_usage_when_no_real_calls_recorded():
    with patch("aryx.api.ask_api.llm_runtime.get_turn_usage", lambda: None):
        usage = api._current_turn_usage_dict()
    assert usage == {
        "prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
        "menial_model": "cpq-engine", "answer_model": "cpq-engine",
    }


def test_default_usage_when_zero_calls_recorded():
    fake = {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
            "calls": 0, "models": []}
    with patch("aryx.api.ask_api.llm_runtime.get_turn_usage", lambda: fake):
        usage = api._current_turn_usage_dict()
    assert usage["menial_model"] == "cpq-engine"
    assert usage["prompt_tokens"] == 0


def test_real_usage_when_calls_recorded():
    fake = {"prompt_tokens": 181, "completion_tokens": 38, "latency_ms": 4149,
            "calls": 1, "models": ["gemini-3.5-flash"]}
    with patch("aryx.api.ask_api.llm_runtime.get_turn_usage", lambda: fake):
        usage = api._current_turn_usage_dict()
    assert usage == {
        "prompt_tokens": 181, "completion_tokens": 38, "latency_ms": 4149,
        "menial_model": "gemini-3.5-flash", "answer_model": "gemini-3.5-flash",
    }


def test_persist_cpq_history_writes_real_usage_to_the_store(monkeypatch):
    fake = {"prompt_tokens": 382, "completion_tokens": 66, "latency_ms": 6595,
            "calls": 1, "models": ["gemini-3.5-flash"]}
    monkeypatch.setattr(api.llm_runtime, "get_turn_usage", lambda: fake)

    captured: dict = {}

    class _FakeStore:
        def __init__(self, dsn):
            pass

        def append(self, workspace_id, question, answer, tools_called,
                   entity_ids, usage):
            captured["usage"] = usage

        def close(self):
            pass

    monkeypatch.setattr(api, "AskHistoryStore", _FakeStore)

    api._persist_cpq_history(1, "whichever plan you decide", "1 Year or 2 Year?")

    assert captured["usage"] == {
        "prompt_tokens": 382, "completion_tokens": 66, "latency_ms": 6595,
        "menial_model": "gemini-3.5-flash", "answer_model": "gemini-3.5-flash",
    }


def test_persist_cpq_history_falls_back_to_default_when_no_real_calls(monkeypatch):
    monkeypatch.setattr(api.llm_runtime, "get_turn_usage", lambda: None)

    captured: dict = {}

    class _FakeStore:
        def __init__(self, dsn):
            pass

        def append(self, workspace_id, question, answer, tools_called,
                   entity_ids, usage):
            captured["usage"] = usage

        def close(self):
            pass

    monkeypatch.setattr(api, "AskHistoryStore", _FakeStore)

    api._persist_cpq_history(1, "1", "SmartConnect — choose one: 1 Year, 2 Year")

    assert captured["usage"] == {
        "prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
        "menial_model": "cpq-engine", "answer_model": "cpq-engine",
    }
