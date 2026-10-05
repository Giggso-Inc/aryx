"""JobStore.sweep_stale_heartbeat() -- §0, 2026-10-04.

Kept in its own file rather than alongside TestSweepStaleJobs in
test_oci_backends.py: that file's unrelated pre-existing OCI-auth test
fixtures (dummy credentials/key content for exercising _get_auth()) make
the whole file trip a pre-commit secret scan once ANY part of it is
staged, regardless of which lines actually changed.
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock


class TestSweepStaleHeartbeat(unittest.TestCase):
    """Same contract as JobStore.sweep_stale(), separate method/query/threshold."""

    def _make_store_with_mock_pool(self, rowcount: int = 0):
        """Return a JobStore whose pool is fully mocked."""
        from aryx.store.job_store import JobStore

        mock_cur = MagicMock()
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_cur.rowcount = rowcount

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cur

        mock_pool = MagicMock()
        mock_pool.connection.return_value = mock_conn

        store = JobStore.__new__(JobStore)
        store._pool = mock_pool
        return store, mock_cur

    def test_returns_zero_when_no_stale_jobs(self) -> None:
        store, _ = self._make_store_with_mock_pool(rowcount=0)
        assert store.sweep_stale_heartbeat(10) == 0

    def test_returns_count_of_swept_jobs(self) -> None:
        store, _ = self._make_store_with_mock_pool(rowcount=3)
        assert store.sweep_stale_heartbeat(10) == 3

    def test_executes_with_timeout_parameter(self) -> None:
        store, mock_cur = self._make_store_with_mock_pool(rowcount=1)
        store.sweep_stale_heartbeat(10)
        call_args = mock_cur.execute.call_args
        # Second positional arg is the params tuple -- must contain the timeout value
        params = call_args[0][1]
        assert params == (10,)

    def test_logs_warning_when_rows_swept(self) -> None:
        import logging
        store, _ = self._make_store_with_mock_pool(rowcount=2)
        with self.assertLogs("aryx.store.job_store", level=logging.WARNING):
            store.sweep_stale_heartbeat(10)

    def test_no_log_when_zero_rows(self) -> None:
        import logging as _logging
        store, _ = self._make_store_with_mock_pool(rowcount=0)
        # assertLogs raises AssertionError if no logs emitted -- that's the pass condition
        with self.assertRaises(AssertionError):
            with self.assertLogs("aryx.store.job_store", level=_logging.WARNING):
                store.sweep_stale_heartbeat(10)

    def test_uses_a_different_query_than_sweep_stale(self) -> None:
        """Distinct SQL file/error text -- not just a thin alias for sweep_stale()."""
        from aryx.queries import load
        assert load("sweep_stale_jobs_heartbeat") != load("sweep_stale_jobs")
        assert "worker lost" in load("sweep_stale_jobs_heartbeat")

    def test_query_scoped_to_running_cpq_ingestion_jobs_only(self) -> None:
        """PR review M1 (2026-10-04): the heartbeat additions (on_progress
        threading) only cover the cpq XML raw-graph resolve loop and the
        chunked resolver -- every other job type/stage (document ingestion,
        REST/DB ingest, the final graph projection, and a QUEUED job still
        waiting behind others for a free ARYX_INGEST_WORKERS slot) can
        legitimately go silent far longer than the 10-minute default without
        anything being wrong. Sweeping those too would fail healthy jobs.
        The query must restrict itself to status='running' (never 'queued')
        AND a stage naming the one path this PR actually instruments."""
        from aryx.queries import load
        sql = load("sweep_stale_jobs_heartbeat").lower()
        assert "status = 'running'" in sql
        assert "not in" not in sql  # the old, too-broad filter shape
        assert "cpq ingestion" in sql

    def test_query_text_survives_psycopg_placeholder_parsing(self) -> None:
        """PR review round 7, High: psycopg's %-style parameter parser
        scans the WHOLE query text for '%' sequences, not just the real
        %s placeholder -- a literal '%CPQ Ingestion%' LIKE pattern with
        single '%' is indistinguishable to it from an unrecognized
        placeholder ('%C' is not '%s'/'%b'/'%t'), and execute() raises
        ProgrammingError before ever reaching Postgres. The 6 mocked-cursor
        tests above never execute the real query text, so none of them
        caught this: the heartbeat sweep silently never ran on Postgres
        until main_lifespan's own broad except swallowed the error. Single
        '%' inside a LIKE literal must be escaped as '%%'.

        Re-implements psycopg._queries's own acceptance rule (every bare
        '%' must be followed by '%', '(name)s'/'b'/'t', or a plain
        's'/'b'/'t') rather than importing psycopg._queries directly --
        several other test files in this suite (test_oci_backends.py,
        test_datasource_store.py, test_discovery_store.py) replace
        sys.modules['psycopg'] with a bare types.ModuleType at module
        import time (not inside a fixture), the same class of
        collection-order test-isolation hazard round 5 hit with oracledb
        (see test_oracle_migrate.py's create=True fix) -- importing the
        real submodule here would be a coin flip depending on which test
        files pytest already collected first. Reads the file directly
        (not through aryx.queries.load()) since this dev environment's own
        settings default effective_db_backend() to 'oci', which load()
        would route to the Oracle override instead of this file."""
        import re
        from pathlib import Path

        import aryx.queries as queries_mod

        sql = (Path(queries_mod.__file__).parent / "sweep_stale_jobs_heartbeat.sql").read_text()
        for m in re.finditer(r"%(?:\([^)]+\))?.", sql):
            placeholder = m.group(0)
            assert placeholder == "%%" or placeholder[-1] in "sbt", (
                f"invalid psycopg placeholder {placeholder!r} -- a literal '%' "
                "in the query text must be escaped as '%%'"
            )


class TestNoResurrectionGuard(unittest.TestCase):
    """update_job_stage / finish_job must not revive a job the heartbeat
    sweep already marked 'failed' (PR review M1) -- otherwise a worker that
    was swept out from under it, but is still actually running, flips the
    row straight back to 'running' on its very next progress report, or
    overwrites 'failed' with 'complete' when it eventually finishes,
    silently erasing the fact that it was ever flagged."""

    def test_update_job_stage_excludes_failed_rows(self) -> None:
        from aryx.queries import load
        sql = load("update_job_stage").lower()
        assert "status != 'failed'" in sql or "status <> 'failed'" in sql

    def test_finish_job_excludes_failed_rows(self) -> None:
        from aryx.queries import load
        sql = load("finish_job").lower()
        assert "status != 'failed'" in sql or "status <> 'failed'" in sql


if __name__ == "__main__":
    unittest.main()
