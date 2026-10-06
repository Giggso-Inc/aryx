"""Unit tests for OraclePool.connection()'s dead-connection handling.

Live incident, 2026-10-06: a long DELETE's connection was killed server-side
(DPY-4011). The old code called raw.rollback() on that already-dead
connection, which itself raised DPY-1001 -- masking the original DPY-4011 in
the propagated traceback -- then released (not dropped) the dead connection
back to the pool, leaving an unusable slot in rotation until the next
acquire's ping happened to catch it. A later, unrelated request timed out
waiting ~30s for a pool slot in the meantime (matching wait_timeout=30000).

These tests construct OraclePool via __new__ (bypassing __init__, which
requires a real oracledb install + live DSN + settings) and inject a
MagicMock in place of the internal oracledb pool, so no live Oracle
connection or network access is needed.
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from aryx.store.oracle_connection_pool import OraclePool, _is_dead_connection_error


def _make_pool(raw_connection: MagicMock) -> tuple[OraclePool, MagicMock]:
    pool = OraclePool.__new__(OraclePool)
    inner = MagicMock()
    inner.acquire.return_value = raw_connection
    pool._pool = inner
    return pool, inner


class TestIsDeadConnectionError(unittest.TestCase):
    def test_dpy_4011_is_dead(self) -> None:
        self.assertTrue(_is_dead_connection_error(Exception("DPY-4011: the database or network closed the connection")))

    def test_dpy_1001_is_dead(self) -> None:
        self.assertTrue(_is_dead_connection_error(Exception("DPY-1001: not connected to database")))

    def test_broken_pipe_is_dead(self) -> None:
        self.assertTrue(_is_dead_connection_error(Exception("Broken pipe")))

    def test_unrelated_error_is_not_dead(self) -> None:
        self.assertFalse(_is_dead_connection_error(Exception("ORA-00001: unique constraint violated")))


class TestOraclePoolConnectionCleanup(unittest.TestCase):
    def test_clean_exit_commits_and_releases(self) -> None:
        raw = MagicMock()
        pool, inner = _make_pool(raw)

        with pool.connection():
            pass

        raw.commit.assert_called_once()
        raw.rollback.assert_not_called()
        inner.release.assert_called_once_with(raw)
        inner.drop.assert_not_called()

    def test_ordinary_exception_rolls_back_and_releases(self) -> None:
        raw = MagicMock()
        pool, inner = _make_pool(raw)

        with self.assertRaises(ValueError):
            with pool.connection():
                raise ValueError("ORA-00001: unique constraint violated")

        raw.rollback.assert_called_once()
        inner.release.assert_called_once_with(raw)
        inner.drop.assert_not_called()

    def test_dead_connection_error_skips_rollback_and_drops(self) -> None:
        """The core fix: a dead-connection exception must not attempt
        rollback() (which would itself raise and mask the original error,
        per the live 2026-10-06 incident), and the connection must be
        drop()'d, not release()'d, so the pool's slot accounting is
        corrected immediately."""
        raw = MagicMock()
        pool, inner = _make_pool(raw)

        with self.assertRaises(Exception) as ctx:
            with pool.connection():
                raise Exception("DPY-4011: the database or network closed the connection")

        # The original exception propagates unchanged -- not replaced by a
        # secondary DPY-1001 from a rollback() attempt.
        self.assertIn("DPY-4011", str(ctx.exception))
        raw.rollback.assert_not_called()
        inner.drop.assert_called_once_with(raw)
        inner.release.assert_not_called()

    def test_dead_connection_detected_even_if_rollback_would_have_raised(self) -> None:
        """Simulates the exact live failure mode: if rollback() were called
        on this connection it would raise DPY-1001 (it's already dead). The
        fix must never call it in the first place."""
        raw = MagicMock()
        raw.rollback.side_effect = Exception("DPY-1001: not connected to database")
        pool, inner = _make_pool(raw)

        with self.assertRaises(Exception) as ctx:
            with pool.connection():
                raise Exception("DPY-4011: the database or network closed the connection")

        self.assertIn("DPY-4011", str(ctx.exception))
        raw.rollback.assert_not_called()
        inner.drop.assert_called_once_with(raw)

    def test_raven_log_called_on_dead_connection(self) -> None:
        raw = MagicMock()
        pool, _inner = _make_pool(raw)

        with patch("aryx.store.oracle_connection_pool.raven_log") as raven_log_mock:
            with self.assertRaises(Exception):
                with pool.connection():
                    raise Exception("DPY-4011: the database or network closed the connection")

        raven_log_mock.assert_called_once()
        args, kwargs = raven_log_mock.call_args
        self.assertEqual(args[0], "WARN")
        self.assertEqual(kwargs["context"]["result"], "error")


if __name__ == "__main__":
    unittest.main()
