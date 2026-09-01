"""BmlEvaluator's Tier-2 LLM calls must record real token usage instead of
discarding it — docs/CPQ_Usage_Reporting_Gap issue #3.

Root cause: every _evaluate_llm_* method previously called
llm_runtime.chat("answer", sys_p, user_p)[0], indexing only the response
text and throwing away the (prompt_tokens, completion_tokens) the call
actually cost — unrecoverable after the fact, not just unreported. Fixed
by capturing the full tuple and accumulating into self.stats via the new
_record_llm_usage helper.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from aryx.cpq.bml import BmlEvaluator


def _fake_chat(reply_json: str, prompt_tokens: int, completion_tokens: int):
    return lambda tier, sys_p, user_p: (reply_json, prompt_tokens, completion_tokens)


@pytest.fixture(autouse=True)
def _block_real_rdb_access(monkeypatch):
    """BmlEvaluator's durable Tier-2 cache (_durable_get/_durable_put) hits
    aryx.store.pool.get_pool -- on a host with no route to the `postgres`
    compose service this hangs on connection for ~30s per call instead of
    failing fast (same class of issue as docs/config_consistency_issues_
    2026-07-30.md Issue 9 / tests/test_cpq_product_switch.py's own fix).
    Every call site already wraps this in try/except and degrades to "no
    cached result" on failure, so failing fast here is behavior-preserving,
    just fast.
    """
    def _fail_fast(dsn, min_size=2, max_size=10):
        raise RuntimeError("real RDB access attempted from an offline unit test")
    monkeypatch.setattr("aryx.store.pool.get_pool", _fail_fast)


def test_hide_for_script_tier2_records_real_token_usage():
    ev = BmlEvaluator(scripts={}, use_llm=True, workspace_id=1, tier2_max_per_turn=10)
    with patch("aryx.llm_runtime.chat", _fake_chat('{"hide": true}', 120, 15)):
        result = ev.hide_for_script("if (x==\"unparseable by tier1\") { hide=true; }", {"x": "y"})
    assert result is True
    assert ev.stats["prompt_tokens"] == 120
    assert ev.stats["completion_tokens"] == 15


def test_condition_holds_tier2_records_real_token_usage():
    ev = BmlEvaluator(scripts={}, use_llm=True, workspace_id=1, tier2_max_per_turn=10)
    with patch("aryx.llm_runtime.chat", _fake_chat('{"condition_true": false}', 80, 10)):
        result = ev.condition_holds("some genuinely unparseable script body", {"x": "y"})
    assert result is False
    assert ev.stats["prompt_tokens"] == 80
    assert ev.stats["completion_tokens"] == 10


def test_allowed_values_for_script_tier2_records_real_token_usage():
    ev = BmlEvaluator(scripts={}, use_llm=True, workspace_id=1, tier2_max_per_turn=10)
    with patch("aryx.llm_runtime.chat",
               _fake_chat('{"allowed_values": ["A", "B"]}', 200, 25)):
        result = ev.allowed_values_for_script("unparseable script body", {"x": "y"})
    assert result == ["A", "B"]
    assert ev.stats["prompt_tokens"] == 200
    assert ev.stats["completion_tokens"] == 25


def test_usage_accumulates_across_multiple_tier2_calls_in_one_turn():
    """One BmlEvaluator instance lives for exactly one turn — its stats
    must accumulate across every Tier-2 call made during that turn, not
    just reflect the last one."""
    ev = BmlEvaluator(scripts={}, use_llm=True, workspace_id=1, tier2_max_per_turn=10)
    with patch("aryx.llm_runtime.chat", _fake_chat('{"hide": true}', 100, 10)):
        ev.hide_for_script("unparseable script one", {"x": "y"})
    with patch("aryx.llm_runtime.chat", _fake_chat('{"condition_true": true}', 50, 5)):
        ev.condition_holds("unparseable script two", {"x": "y"})
    assert ev.stats["prompt_tokens"] == 150
    assert ev.stats["completion_tokens"] == 15


def test_llm_call_exception_records_no_usage():
    """An LLM call that raises (network failure, provider error) genuinely
    cost nothing recoverable — must not add phantom usage, and must still
    resolve to the same safe 'unknown' outcome as before."""
    ev = BmlEvaluator(scripts={}, use_llm=True, workspace_id=1, tier2_max_per_turn=10)
    with patch("aryx.llm_runtime.chat", side_effect=RuntimeError("provider unavailable")):
        result = ev.hide_for_script("unparseable script", {"x": "y"})
    assert result is None
    assert ev.stats["prompt_tokens"] == 0
    assert ev.stats["completion_tokens"] == 0


def test_ask_worthy_tier2_records_real_token_usage():
    ev = BmlEvaluator(scripts={}, use_llm=True, workspace_id=1, tier2_max_per_turn=10)
    with patch("aryx.llm_runtime.chat", _fake_chat('{"ask_worthy": true}', 60, 8)):
        result = ev.classify_ask_worthy(
            attr_label="Domain Name", rule_message="must be set",
            rule_script="return validate(domainName);", attr_key=42,
        )
    assert result is True
    assert ev.stats["prompt_tokens"] == 60
    assert ev.stats["completion_tokens"] == 8
