"""Rule-trace write timeout + circuit breaker (dev-rv-msi #363), reworked for Oracle call_timeout.

Oracle behaviour is mock-tested only; needs a live ADB check.
"""
from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from aryx.store import rule_trace_store as rts
from aryx.store.rule_trace_store import RuleTraceStore


def _settings(enabled=True, backend="postgres", ms=5000, threshold=3):
    return SimpleNamespace(
        cpq_rule_trace_write_timeout_enabled=enabled,
        cpq_rule_trace_write_timeout_ms=ms,
        cpq_rule_trace_breaker_threshold=threshold,
        effective_db_backend=lambda: backend,
    )


def _pool():
    cursor = MagicMock()
    conn = MagicMock()
    conn.call_timeout = 111
    conn.cursor.return_value.__enter__.return_value = cursor
    pool = MagicMock()
    pool.connection.return_value.__enter__.return_value = conn
    return pool, conn, cursor


@pytest.fixture(autouse=True)
def _reset_breaker():
    rts._fail_counts.clear()
    rts._open_runs.clear()
    yield
    rts._fail_counts.clear()
    rts._open_runs.clear()


def _store(pool):
    with patch("aryx.store.rule_trace_store.get_pool", return_value=pool):
        return RuleTraceStore("x")


def _append(store, run="r1"):
    store.append_entry(run, 1, 0, "hiding", "H1", "vn", "hide", None)


def test_postgres_set_local_literal_before_insert():
    pool, _conn, cur = _pool()
    with patch("aryx.store.rule_trace_store.get_settings", return_value=_settings()):
        _append(_store(pool))
    assert cur.execute.call_args_list[0][0] == ("SET LOCAL statement_timeout = 5000",)
    assert cur.execute.call_count == 2


def test_open_session_bounded():
    pool, _c, cur = _pool()
    with patch("aryx.store.rule_trace_store.get_settings", return_value=_settings()):
        _store(pool).open_session("r1", 1, "P", "f")
    assert cur.execute.call_args_list[0][0] == ("SET LOCAL statement_timeout = 5000",)


def test_flag_off_single_execute_no_set():
    pool, conn, cur = _pool()
    with patch("aryx.store.rule_trace_store.get_settings", return_value=_settings(enabled=False)):
        _append(_store(pool))
    assert cur.execute.call_count == 1
    assert conn.call_timeout == 111


def test_oracle_call_timeout_on_connection_and_restored():
    pool, conn, cur = _pool()
    seen = []
    cur.execute.side_effect = lambda *a, **k: seen.append(conn.call_timeout)
    with patch("aryx.store.rule_trace_store.get_settings", return_value=_settings(backend="oci")):
        _append(_store(pool))
    assert seen == [5000]
    assert conn.call_timeout == 111
    assert cur.execute.call_count == 1  # no SET statement on Oracle


def test_oracle_call_timeout_restored_on_exception():
    pool, conn, cur = _pool()
    cur.execute.side_effect = RuntimeError("ORA-03156: call timeout")
    with patch("aryx.store.rule_trace_store.get_settings", return_value=_settings(backend="oci")):
        with pytest.raises(RuntimeError):
            _append(_store(pool))
    assert conn.call_timeout == 111


def test_exception_propagates_and_timeout_warns(caplog):
    pool, _c, cur = _pool()
    cur.execute.side_effect = [None, RuntimeError("canceling statement due to statement timeout")]
    with patch("aryx.store.rule_trace_store.get_settings", return_value=_settings()), \
         caplog.at_level(logging.WARNING):
        with pytest.raises(RuntimeError, match="statement timeout"):
            _append(_store(pool))
    assert any("timed out" in r.message for r in caplog.records)


def test_breaker_opens_after_n_failures_then_skips_and_logs_once(caplog):
    pool, _c, cur = _pool()
    cur.execute.side_effect = RuntimeError("down")
    with patch("aryx.store.rule_trace_store.get_settings", return_value=_settings(backend="oci", threshold=3)), \
         caplog.at_level(logging.ERROR):
        st = _store(pool)
        for _ in range(3):
            with pytest.raises(RuntimeError):
                _append(st)
        calls = cur.execute.call_count
        _append(st)  # breaker open: silent no-op
        _append(st)
        assert cur.execute.call_count == calls
        with pytest.raises(RuntimeError):  # other run unaffected
            _append(st, run="r2")
    assert sum("circuit breaker open" in r.message for r in caplog.records) == 1


def test_breaker_resets_on_success():
    pool, _c, cur = _pool()
    with patch("aryx.store.rule_trace_store.get_settings", return_value=_settings(backend="oci", threshold=3)):
        st = _store(pool)
        cur.execute.side_effect = RuntimeError("down")
        for _ in range(2):
            with pytest.raises(RuntimeError):
                _append(st)
        cur.execute.side_effect = None
        _append(st)
        assert "r1" not in rts._fail_counts
        cur.execute.side_effect = RuntimeError("down")
        for _ in range(2):
            with pytest.raises(RuntimeError):
                _append(st)
        assert "r1" not in rts._open_runs
