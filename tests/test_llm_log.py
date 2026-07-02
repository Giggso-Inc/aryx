"""Unit tests for llm._log_llm_call — no live DB or OCI required.

_log_llm_call uses local imports (from aryx.store.pool import get_pool),
so patches must target the source module. aryx.store.pool depends on psycopg_pool
which is not available in the minimal test env, so we stub both aryx.store and
aryx.store.pool into sys.modules before any import.
"""
from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import MagicMock, patch


def _stub_store_pool() -> None:
    """Register bare stub modules to avoid psycopg / psycopg_pool deps.

    mock._dot_lookup resolves dotted paths via getattr on the parent module
    (not just sys.modules), so we must also set the child as an attribute on
    its parent after importing the top-level aryx package.
    """
    import aryx as _aryx  # safe — aryx/__init__.py has no psycopg imports

    if "aryx.store" not in sys.modules:
        store_mod = types.ModuleType("aryx.store")
        sys.modules["aryx.store"] = store_mod
    else:
        store_mod = sys.modules["aryx.store"]
    if not hasattr(_aryx, "store"):
        _aryx.store = store_mod  # type: ignore[attr-defined]

    if "aryx.store.pool" not in sys.modules:
        pool_mod = types.ModuleType("aryx.store.pool")
        pool_mod.get_pool = MagicMock()  # type: ignore[attr-defined]
        sys.modules["aryx.store.pool"] = pool_mod
    else:
        pool_mod = sys.modules["aryx.store.pool"]
    if not hasattr(store_mod, "pool"):
        store_mod.pool = pool_mod  # type: ignore[attr-defined]


_stub_store_pool()


class TestLogLlmCall(unittest.TestCase):
    """_log_llm_call is best-effort: no-op when DSN unavailable, swallows on error."""

    def test_no_op_when_effective_dsn_raises(self) -> None:
        """OCI mode with no ARYX_OCI_ADB_DSN: effective_dsn() raises, get_pool not called."""
        from aryx.llm import _log_llm_call
        mock_settings = MagicMock()
        mock_settings.effective_dsn.side_effect = RuntimeError("ARYX_OCI_ADB_DSN must be set")
        with patch("aryx.config.get_settings", return_value=mock_settings):
            with patch("aryx.store.pool.get_pool") as mock_pool:
                _log_llm_call("cheap", "cohere.command-r", "oci", 100, 50, 300)
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
        mock_pool_inst = MagicMock()
        mock_pool_inst.connection.return_value = mock_conn_ctx

        mock_settings = MagicMock()
        mock_settings.effective_dsn.return_value = "fake-dsn"
        with patch("aryx.config.get_settings", return_value=mock_settings):
            with patch("aryx.store.pool.get_pool", return_value=mock_pool_inst):
                with patch("aryx.queries.load", return_value="INSERT ...") as mock_load:
                    _log_llm_call("cheap", "cohere.command-r", "oci", 100, 50, 300)
                    mock_load.assert_called_once_with("insert_llm_call")

        mock_cur.execute.assert_called_once()
        _sql, params = mock_cur.execute.call_args[0]
        self.assertEqual(params[6], "pipeline")

    def test_exception_swallowed_silently(self) -> None:
        from aryx.llm import _log_llm_call
        mock_settings = MagicMock()
        mock_settings.effective_dsn.return_value = "fake-dsn"
        with patch("aryx.config.get_settings", return_value=mock_settings):
            with patch("aryx.store.pool.get_pool", side_effect=RuntimeError("pool unavailable")):
                try:
                    _log_llm_call("cheap", "cohere.command-r", "oci", 10, 5, 100)
                except RuntimeError:
                    self.fail("_log_llm_call should swallow exceptions")


if __name__ == "__main__":
    unittest.main()
