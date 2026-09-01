"""Regression coverage for `_llm_classify_is_ask_in_scope` (the Ask
scope gate added to fix the "outside what I track" blanket refusal).

Confirms the fail-open contract explicitly: only an explicit
`out_of_scope` classification should reject a question. A malformed
reply or an LLM-call exception must NOT be treated as out-of-scope —
that would silently reproduce the original bug under a different
trigger.
"""
from __future__ import annotations

from unittest.mock import patch

from aryx.api.ask_api import _llm_classify_is_ask_in_scope


def test_in_scope_classification_returns_true():
    fake_reply = '{"classification": "in_scope"}'
    with patch("aryx.api.ask_api.llm_runtime.chat", return_value=(fake_reply, 10, 5)):
        result = _llm_classify_is_ask_in_scope(
            "what are the entities present in suppliers?", workspace_id=1)
    assert result is True


def test_explicit_out_of_scope_classification_returns_false():
    fake_reply = '{"classification": "out_of_scope"}'
    with patch("aryx.api.ask_api.llm_runtime.chat", return_value=(fake_reply, 10, 5)):
        result = _llm_classify_is_ask_in_scope(
            "what's the weather like today?", workspace_id=1)
    assert result is False


def test_malformed_json_fails_open_to_in_scope():
    with patch("aryx.api.ask_api.llm_runtime.chat", return_value=("not json at all", 10, 5)):
        result = _llm_classify_is_ask_in_scope("show me the underlying records", workspace_id=1)
    assert result is True


def test_llm_exception_fails_open_to_in_scope():
    with patch("aryx.api.ask_api.llm_runtime.chat", side_effect=RuntimeError("provider unavailable")):
        result = _llm_classify_is_ask_in_scope("show me the underlying records", workspace_id=1)
    assert result is True


def test_unrecognized_classification_value_fails_open_to_in_scope():
    fake_reply = '{"classification": "maybe"}'
    with patch("aryx.api.ask_api.llm_runtime.chat", return_value=(fake_reply, 10, 5)):
        result = _llm_classify_is_ask_in_scope("show me the underlying records", workspace_id=1)
    assert result is True
