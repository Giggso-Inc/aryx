"""llm_runtime's per-turn real-usage accumulator — docs/
CPQ_Usage_Reporting_Gap issues #1/#2: every LLM call in the codebase goes
through llm_runtime.chat(), so recording usage there (not at each of the
dozens of individual call sites) captures real cost from any current or
future caller automatically.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from aryx import llm_runtime


def _fake_complete_text(model, tier, system, user, think=False):
    return ("some reply", 42, 7)


@pytest.fixture(autouse=True)
def _isolate_turn_usage():
    """_turn_usage is a ContextVar that otherwise persists across tests
    sharing the same thread (pytest's default) -- explicitly clear it
    before and after each test so tests are order-independent."""
    token = llm_runtime._turn_usage.set(None)
    try:
        yield
    finally:
        llm_runtime._turn_usage.reset(token)


def test_get_turn_usage_is_none_before_reset():
    # No reset_turn_usage() call in this (isolated) context must report
    # None, not a zeroed dict — callers must be able to tell "never opted
    # in" apart from "opted in, zero calls happened".
    assert llm_runtime.get_turn_usage() is None


def test_reset_then_no_calls_reports_zero_calls():
    llm_runtime.reset_turn_usage()
    usage = llm_runtime.get_turn_usage()
    assert usage == {
        "prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
        "calls": 0, "models": [],
    }


def test_single_chat_call_is_recorded():
    llm_runtime.reset_turn_usage()
    with patch("aryx.llm_runtime.complete_text", _fake_complete_text), \
         patch.object(llm_runtime, "_log_call", lambda *a, **k: None):
        llm_runtime.chat("menial", "sys", "user")
    usage = llm_runtime.get_turn_usage()
    assert usage["prompt_tokens"] == 42
    assert usage["completion_tokens"] == 7
    assert usage["calls"] == 1
    assert usage["latency_ms"] >= 0


def test_multiple_chat_calls_accumulate():
    llm_runtime.reset_turn_usage()
    with patch("aryx.llm_runtime.complete_text", _fake_complete_text), \
         patch.object(llm_runtime, "_log_call", lambda *a, **k: None):
        llm_runtime.chat("menial", "sys", "user")
        llm_runtime.chat("answer", "sys", "user")
    usage = llm_runtime.get_turn_usage()
    assert usage["prompt_tokens"] == 84
    assert usage["completion_tokens"] == 14
    assert usage["calls"] == 2


def test_reset_clears_prior_turn_totals():
    llm_runtime.reset_turn_usage()
    with patch("aryx.llm_runtime.complete_text", _fake_complete_text), \
         patch.object(llm_runtime, "_log_call", lambda *a, **k: None):
        llm_runtime.chat("menial", "sys", "user")
    assert llm_runtime.get_turn_usage()["calls"] == 1

    llm_runtime.reset_turn_usage()
    assert llm_runtime.get_turn_usage()["calls"] == 0


def test_failed_chat_call_records_nothing():
    llm_runtime.reset_turn_usage()

    def _raise(*a, **k):
        raise RuntimeError("provider unavailable")

    with patch("aryx.llm_runtime.complete_text", _raise):
        try:
            llm_runtime.chat("menial", "sys", "user")
        except RuntimeError:
            pass
    usage = llm_runtime.get_turn_usage()
    assert usage["calls"] == 0
    assert usage["prompt_tokens"] == 0
