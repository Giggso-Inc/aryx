"""Tests for aryx.store.rule_trace_store.RuleTraceStore -- mocked pool/cursor,
no real Postgres (same pattern as test_discoveries_durable.py).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from aryx.store.rule_trace_store import RuleTraceStore


def _mock_pool_and_cursor():
    cursor = MagicMock()
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    pool = MagicMock()
    pool.connection.return_value.__enter__.return_value = conn
    return pool, cursor


class TestOpenSession:
    def test_open_session_executes_insert(self):
        pool, cursor = _mock_pool_and_cursor()
        with patch("aryx.store.rule_trace_store.get_pool", return_value=pool):
            store = RuleTraceStore("postgresql://x")
            store.open_session("run-1", 1, "ApxNextConfig", "ApxNextConfig_20260101T000000")
        cursor.execute.assert_called_once()
        args = cursor.execute.call_args[0][1]
        assert args == ("run-1", 1, "ApxNextConfig", "ApxNextConfig_20260101T000000")


class TestAppendEntry:
    def test_append_entry_executes_insert_per_call(self):
        pool, cursor = _mock_pool_and_cursor()
        with patch("aryx.store.rule_trace_store.get_pool", return_value=pool):
            store = RuleTraceStore("postgresql://x")
            store.append_entry("run-1", 1, 0, "hiding", "H1", "vn", "hide", None)
            store.append_entry("run-1", 2, 0, "constraint", "C1", "vn2", "allowed=[X]", "script")
        assert cursor.execute.call_count == 2  # one row per fire, never buffered


class TestSealSession:
    def test_seal_session_returns_true_when_row_updated(self):
        pool, cursor = _mock_pool_and_cursor()
        cursor.rowcount = 1
        with patch("aryx.store.rule_trace_store.get_pool", return_value=pool):
            store = RuleTraceStore("postgresql://x")
            sealed = store.seal_session("run-1", status="post_approval")
        assert sealed is True

    def test_seal_session_returns_false_when_already_sealed(self):
        pool, cursor = _mock_pool_and_cursor()
        cursor.rowcount = 0
        with patch("aryx.store.rule_trace_store.get_pool", return_value=pool):
            store = RuleTraceStore("postgresql://x")
            sealed = store.seal_session("run-1", status="post_approval")
        assert sealed is False


class TestSweepOrphans:
    def test_sweep_orphans_seals_every_open_session_past_timeout(self):
        pool, cursor = _mock_pool_and_cursor()
        cursor.fetchall.return_value = [
            ("run-a", 1, "ApxNextConfig", "file-a", "2020-01-01"),
            ("run-b", 1, "Sl3500e", "file-b", "2020-01-01"),
        ]
        cursor.rowcount = 1
        with patch("aryx.store.rule_trace_store.get_pool", return_value=pool):
            store = RuleTraceStore("postgresql://x")
            sealed = store.sweep_orphans(timeout_hours=24)
        assert sealed == ["run-a", "run-b"]

    def test_sweep_orphans_returns_empty_when_none_past_timeout(self):
        pool, cursor = _mock_pool_and_cursor()
        cursor.fetchall.return_value = []
        with patch("aryx.store.rule_trace_store.get_pool", return_value=pool):
            store = RuleTraceStore("postgresql://x")
            sealed = store.sweep_orphans(timeout_hours=24)
        assert sealed == []
