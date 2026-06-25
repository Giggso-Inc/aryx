"""Unit tests for llm._log_llm_call — no live DB or OCI required.

_log_llm_call uses local imports (from aryx.store.pool import get_pool),
so patches must target the source module, not aryx.llm.
"""
from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch


class TestLogLlmCall(unittest.TestCase):
    """_log_llm_call is best-effort: no-op when DSN is absent, swallows on error."""

    def test_no_op_when_dsn_empty(self) -> None:
        from aryx.llm import _log_llm_call
        with patch.dict("os.environ", {"ARYX_RDB_DSN": ""}):
            with patch("aryx.store.pool.get_pool") as mock_pool:
                _log_llm_call("cheap", "cohere.command-r", "oci", 100, 50, 300)
                mock_pool.assert_not_called()

    def test_no_op_when_dsn_absent(self) -> None:
        from aryx.llm import _log_llm_call
        env = {k: v for k, v in os.environ.items() if k != "ARYX_RDB_DSN"}
        with patch.dict("os.environ", env, clear=True):
            with patch("aryx.store.pool.get_pool") as mock_pool:
                _log_llm_call("frontier", "cohere.command-r-plus", "oci", 200, 80, 500)
                mock_pool.assert_not_called()

    def test_executes_insert_when_dsn_set(self) -> None:
        from aryx.llm import _log_llm_call
        mock_cur = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_cur)
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_ctx
        mock_conn_ctx = MagicMock()
        mock_conn_ctx.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn_ctx.__exit__ = MagicMock(return_value=False)
        mock_pool = MagicMock()
        mock_pool.connection.return_value = mock_conn_ctx

        with patch.dict("os.environ", {"ARYX_RDB_DSN": "fake-dsn"}):
            with patch("aryx.store.pool.get_pool", return_value=mock_pool):
                with patch("aryx.queries.load", return_value="INSERT ...") as mock_load:
                    _log_llm_call("cheap", "cohere.command-r", "oci", 100, 50, 300)
                    mock_load.assert_called_once_with("insert_llm_call")

        mock_cur.execute.assert_called_once()
        _sql, params = mock_cur.execute.call_args[0]
        self.assertEqual(params[6], "pipeline")

    def test_exception_swallowed_silently(self) -> None:
        from aryx.llm import _log_llm_call
        with patch.dict("os.environ", {"ARYX_RDB_DSN": "fake-dsn"}):
            with patch("aryx.store.pool.get_pool", side_effect=RuntimeError("pool unavailable")):
                try:
                    _log_llm_call("cheap", "cohere.command-r", "oci", 10, 5, 100)
                except RuntimeError:
                    self.fail("_log_llm_call should swallow exceptions")


if __name__ == "__main__":
    unittest.main()
