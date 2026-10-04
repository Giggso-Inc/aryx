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


if __name__ == "__main__":
    unittest.main()
