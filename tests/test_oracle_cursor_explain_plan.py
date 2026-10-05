"""Automatic EXPLAIN PLAN capture on slow Oracle statements (§4, 2026-10-04,
docs/ingestion/CPQ_XML_CONFIRM_RESOLVE_PERFORMANCE_ISSUES_2026-10-04.md).

No live Oracle session is used -- the connection/cursor objects are plain
mocks shaped like oracledb's API (cur.connection.cursor(), .execute(),
.fetchall(), .close()).
"""
from __future__ import annotations

from unittest.mock import MagicMock, call

import pytest

from aryx.store.oracle_cursor import (
    SLOW_STATEMENT_MS,
    _capture_explain_plan,
    _last_explain_plan_capture,
    _log_stmt_ok,
    _should_capture_explain_plan,
)


@pytest.fixture(autouse=True)
def _reset_explain_plan_rate_limit():
    """_last_explain_plan_capture is module-level state (PR review N5) --
    reset it around every test so one test's capture doesn't suppress
    another's that happens to reuse the same `op` string."""
    _last_explain_plan_capture.clear()
    yield
    _last_explain_plan_capture.clear()


def _mock_cursor_with_plan(plan_rows):
    """A cursor whose .connection.cursor() returns a fresh mock cursor that
    yields plan_rows (list of (line,) tuples) from fetchall()."""
    plan_cur = MagicMock()
    plan_cur.fetchall.return_value = plan_rows
    conn = MagicMock()
    conn.cursor.return_value = plan_cur
    cur = MagicMock()
    cur.connection = conn
    return cur, plan_cur


# ── _capture_explain_plan ────────────────────────────────────────────────────

def test_capture_returns_joined_plan_text():
    cur, plan_cur = _mock_cursor_with_plan([
        ("Plan hash value: 123",), ("TABLE ACCESS FULL ARYX_DATASOURCE",),
    ])

    result = _capture_explain_plan(cur, "SELECT * FROM aryx_datasource WHERE workspace_id = :1")

    assert result == "Plan hash value: 123\nTABLE ACCESS FULL ARYX_DATASOURCE"


def test_capture_uses_a_fresh_cursor_never_the_caller_s_own():
    """Reusing the caller's own cursor would discard an active, unfetched
    result set out from under it -- must always go through
    cur.connection.cursor() for a separate cursor."""
    cur, plan_cur = _mock_cursor_with_plan([("plan line",)])

    _capture_explain_plan(cur, "SELECT 1 FROM dual")

    cur.connection.cursor.assert_called_once()
    cur.execute.assert_not_called()  # the ORIGINAL cursor is never touched
    plan_cur.execute.assert_any_call("EXPLAIN PLAN FOR SELECT 1 FROM dual")


def test_capture_always_closes_the_fresh_cursor():
    cur, plan_cur = _mock_cursor_with_plan([("plan line",)])

    _capture_explain_plan(cur, "SELECT 1 FROM dual")

    plan_cur.close.assert_called_once()


def test_capture_closes_the_fresh_cursor_even_on_failure():
    cur, plan_cur = _mock_cursor_with_plan([])
    plan_cur.execute.side_effect = RuntimeError("ORA-00942: table or view does not exist")

    result = _capture_explain_plan(cur, "SELECT 1 FROM dual")

    assert result is None
    plan_cur.close.assert_called_once()


def test_capture_never_raises_on_any_failure():
    cur = MagicMock()
    cur.connection.cursor.side_effect = RuntimeError("connection pool exhausted")

    result = _capture_explain_plan(cur, "SELECT 1 FROM dual")

    assert result is None  # no exception propagates


def test_capture_returns_none_when_plan_table_output_is_empty():
    cur, _plan_cur = _mock_cursor_with_plan([])

    assert _capture_explain_plan(cur, "SELECT 1 FROM dual") is None


def test_capture_truncates_very_long_plan_text():
    long_line = "x" * 5000
    cur, _plan_cur = _mock_cursor_with_plan([(long_line,)])

    result = _capture_explain_plan(cur, "SELECT 1 FROM dual")

    assert len(result) == 2000


# ── _log_stmt_ok wiring ──────────────────────────────────────────────────────

def test_fast_statement_never_attempts_plan_capture(monkeypatch):
    """Plan capture is a whole extra round-trip -- must never fire for a
    statement under the slow threshold, regardless of whether sql/cur are
    given."""
    called = []
    monkeypatch.setattr("aryx.store.oracle_cursor._capture_explain_plan",
                        lambda cur, sql: called.append(1) or "PLAN")
    import time
    t0 = time.monotonic()  # effectively zero elapsed -- well under threshold

    _log_stmt_ok("SELECT t", "execute", 1, t0, sql="SELECT 1", cur=MagicMock())

    assert called == []


def test_slow_statement_with_sql_and_cur_captures_plan_into_raven_log(monkeypatch):
    captured_context = {}

    def fake_raven_log(level, crit, message, **kwargs):
        captured_context.update(kwargs.get("context", {}))

    monkeypatch.setattr("aryx.store.oracle_cursor.raven_log", fake_raven_log)
    monkeypatch.setattr("aryx.store.oracle_cursor._capture_explain_plan",
                        lambda cur, sql: "TABLE ACCESS FULL ARYX_DATASOURCE")
    import time
    t0 = time.monotonic() - (SLOW_STATEMENT_MS / 1000 + 1)  # force "slow"

    _log_stmt_ok("SELECT aryx_datasource", "execute", 0, t0,
                sql="SELECT * FROM aryx_datasource WHERE workspace_id = :1",
                cur=MagicMock())

    assert captured_context["explain_plan"] == "TABLE ACCESS FULL ARYX_DATASOURCE"
    assert captured_context["duration_ms"] >= SLOW_STATEMENT_MS


def test_slow_statement_without_sql_or_cur_skips_plan_capture_silently(monkeypatch):
    """Backward compatibility: existing call sites that don't pass sql/cur
    (executemany_returning) must keep working exactly as before -- no
    attempted capture, no 'explain_plan' key, no exception."""
    captured_context = {}

    def fake_raven_log(level, crit, message, **kwargs):
        captured_context.update(kwargs.get("context", {}))

    monkeypatch.setattr("aryx.store.oracle_cursor.raven_log", fake_raven_log)
    import time
    t0 = time.monotonic() - (SLOW_STATEMENT_MS / 1000 + 1)

    _log_stmt_ok("INSERT t", "executemany_returning", 5, t0)

    assert "explain_plan" not in captured_context
    assert captured_context["duration_ms"] >= SLOW_STATEMENT_MS


def test_slow_statement_plan_capture_failure_omits_key_without_raising(monkeypatch):
    captured_context = {}

    def fake_raven_log(level, crit, message, **kwargs):
        captured_context.update(kwargs.get("context", {}))

    monkeypatch.setattr("aryx.store.oracle_cursor.raven_log", fake_raven_log)
    monkeypatch.setattr("aryx.store.oracle_cursor._capture_explain_plan",
                        lambda cur, sql: None)
    import time
    t0 = time.monotonic() - (SLOW_STATEMENT_MS / 1000 + 1)

    _log_stmt_ok("SELECT t", "execute", 1, t0, sql="SELECT 1", cur=MagicMock())

    assert "explain_plan" not in captured_context


# ── PR review N5 (2026-10-04): rate-limit plan capture per operation ────────

def test_should_capture_is_true_the_first_time_for_a_new_operation():
    assert _should_capture_explain_plan("SELECT aryx_datasource") is True


def test_should_capture_is_false_immediately_after_capturing():
    assert _should_capture_explain_plan("SELECT aryx_datasource") is True
    assert _should_capture_explain_plan("SELECT aryx_datasource") is False


def test_should_capture_rate_limit_is_per_operation_not_global():
    """A noisy operation being rate-limited must not suppress capture for
    a DIFFERENT, independently-slow operation."""
    assert _should_capture_explain_plan("SELECT aryx_datasource") is True
    assert _should_capture_explain_plan("INSERT aryx_landed_record") is True
    assert _should_capture_explain_plan("SELECT aryx_datasource") is False
    assert _should_capture_explain_plan("INSERT aryx_landed_record") is False


def test_should_capture_allows_again_after_the_rate_limit_window(monkeypatch):
    import time as time_module

    fake_now = [1000.0]
    monkeypatch.setattr(time_module, "monotonic", lambda: fake_now[0])

    assert _should_capture_explain_plan("SELECT aryx_datasource") is True
    assert _should_capture_explain_plan("SELECT aryx_datasource") is False

    fake_now[0] += 601  # just past the 600s window
    assert _should_capture_explain_plan("SELECT aryx_datasource") is True


def test_log_stmt_ok_second_slow_statement_for_same_op_skips_capture(monkeypatch):
    """Integration of the rate limit into _log_stmt_ok itself: a burst of
    slow statements for the SAME op must only trigger one real
    EXPLAIN PLAN attempt, not one per occurrence."""
    captured_contexts = []

    def fake_raven_log(level, crit, message, **kwargs):
        captured_contexts.append(kwargs.get("context", {}))

    capture_calls = []
    monkeypatch.setattr("aryx.store.oracle_cursor.raven_log", fake_raven_log)
    monkeypatch.setattr("aryx.store.oracle_cursor._capture_explain_plan",
                        lambda cur, sql: capture_calls.append(1) or "PLAN")
    import time
    t0 = time.monotonic() - (SLOW_STATEMENT_MS / 1000 + 1)

    for _ in range(3):
        _log_stmt_ok("SELECT aryx_datasource", "execute", 0, t0,
                    sql="SELECT * FROM aryx_datasource WHERE workspace_id = :1",
                    cur=MagicMock())

    assert len(capture_calls) == 1  # only the first of the 3 actually captured
    assert captured_contexts[0].get("explain_plan") == "PLAN"
    assert "explain_plan" not in captured_contexts[1]
    assert "explain_plan" not in captured_contexts[2]
    # All 3 still got their own slow_statement log entry -- only the plan
    # capture itself is rate-limited, not the slow-statement visibility.
    assert len(captured_contexts) == 3
