"""Regression coverage for terminal job-state handling."""
from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

# Stub heavy deps so aryx.store.job_store loads without installed DB packages.
for _mod in ("psycopg", "psycopg.types", "psycopg.types.json",
             "falkordb", "pgvector", "pgvector.psycopg"):
    sys.modules.setdefault(_mod, MagicMock())

sys.modules.setdefault("psycopg_pool", MagicMock(ConnectionPool=MagicMock()))

from aryx.store.job_store import JobStore


def _mock_cursor(rowcount: int) -> MagicMock:
    cur = MagicMock()
    cur.rowcount = rowcount
    return cur


def _mock_pool(cur: MagicMock) -> MagicMock:
    pool = MagicMock()
    conn_ctx = pool.connection.return_value
    conn = conn_ctx.__enter__.return_value
    cur_ctx = conn.cursor.return_value
    cur_ctx.__enter__.return_value = cur
    return pool


def test_update_stage_appends_event_for_active_job():
    cur = _mock_cursor(rowcount=1)
    pool = _mock_pool(cur)

    with patch("aryx.store.job_store.get_pool", return_value=pool), \
         patch("aryx.store.job_store.load",
               side_effect=lambda name: f"sql:{name}"):
        store = JobStore("dsn")
        store.update_stage("job1", "Reading", 30, "Reading 1 file")

    assert cur.execute.call_count == 2
    assert cur.execute.call_args_list[0].args == (
        "sql:update_job_stage", ("Reading", 30, "Reading 1 file", "job1"),
    )
    assert cur.execute.call_args_list[1].args == (
        "sql:insert_job_event", ("job1", "Reading", 30, "Reading 1 file"),
    )


def test_update_stage_ignores_progress_for_terminal_job():
    cur = _mock_cursor(rowcount=0)
    pool = _mock_pool(cur)

    with patch("aryx.store.job_store.get_pool", return_value=pool), \
         patch("aryx.store.job_store.load",
               side_effect=lambda name: f"sql:{name}"):
        store = JobStore("dsn")
        store.update_stage("job1", "Reading", 30, "Reading 1 file")

    assert cur.execute.call_count == 1
    assert cur.execute.call_args_list[0].args == (
        "sql:update_job_stage", ("Reading", 30, "Reading 1 file", "job1"),
    )


def test_finish_updates_active_job():
    cur = _mock_cursor(rowcount=1)
    pool = _mock_pool(cur)

    with patch("aryx.store.job_store.get_pool", return_value=pool), \
         patch("aryx.store.job_store.load",
               side_effect=lambda name: f"sql:{name}"):
        store = JobStore("dsn")
        store.finish("job1", 42, "complete")

    assert cur.execute.call_count == 1
    assert cur.execute.call_args_list[0].args == (
        "sql:finish_job", ("complete", 42, None, "job1"),
    )


def test_finish_ignores_terminal_job():
    cur = _mock_cursor(rowcount=0)
    pool = _mock_pool(cur)

    with patch("aryx.store.job_store.get_pool", return_value=pool), \
         patch("aryx.store.job_store.load",
               side_effect=lambda name: f"sql:{name}"):
        store = JobStore("dsn")
        store.finish("job1", 42, "failed", "cancelled elsewhere")

    assert cur.execute.call_count == 1
    assert cur.execute.call_args_list[0].args == (
        "sql:finish_job", ("failed", 42, "cancelled elsewhere", "job1"),
    )
