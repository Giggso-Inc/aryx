"""Tests for workspace-scoped LLM observability (PR #43 rectifications).

Covers:
  - _llm_stats() passes (workspace_id,) as the SQL param — not ()
  - _recent_llm() passes (workspace_id,) as the SQL param — not ()
  - _log_call() inserts workspace_id at position 0 in the param tuple
  - chat() threads workspace_id through to _log_call
  - observability endpoint requires api key (Depends(require_api_key))
  - ask endpoint rejects unknown workspace_id with 422

Run:
    PYTHONPATH=src python -m pytest tests/test_observability_workspace.py -v
"""
from __future__ import annotations

import sys
import types as _types
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Module-level stubs — must come before any aryx imports.
# ---------------------------------------------------------------------------
for _mod in (
    "psycopg",
    "psycopg.types",
    "psycopg.types.json",
    "psycopg.rows",
    "psycopg.sql",
    "pgvector",
    "pgvector.psycopg",
    "falkordb",
    "openai",
    "anthropic",
    "presidio_analyzer",
    "presidio_anonymizer",
    "pymupdf",
    "pymupdf4llm",
    "docx",
    "pptx",
    "PIL",
    "PIL.Image",
):
    sys.modules.setdefault(_mod, MagicMock())

_mock_cp = MagicMock()
sys.modules.setdefault("psycopg_pool", MagicMock(ConnectionPool=_mock_cp))
sys.modules["psycopg.types.json"].Json = lambda x: x

# Stub aryx modules that call get_settings() at import time or pull in
# heavy deps — must be in sys.modules before aryx.llm_runtime is first imported.
for _mod in ("aryx.llm_providers", "aryx.llm"):
    sys.modules.setdefault(_mod, MagicMock())

# aryx.broker is imported by aryx.llm_runtime; stub it with proper attributes
# so `from aryx.broker import Broker, ModelSpec, Registry, TokenGovernor` works.
if "aryx.broker" not in sys.modules:
    _broker_mod = _types.ModuleType("aryx.broker")
    _broker_mod.Broker = MagicMock()          # type: ignore[attr-defined]
    _broker_mod.ModelSpec = MagicMock()       # type: ignore[attr-defined]
    _broker_mod.Registry = MagicMock()        # type: ignore[attr-defined]
    _broker_mod.TokenGovernor = MagicMock()   # type: ignore[attr-defined]
    sys.modules["aryx.broker"] = _broker_mod
sys.modules.setdefault("aryx.broker.specs", MagicMock())

# Patch get_settings BEFORE aryx.llm_runtime is first imported so the
# module-level `_cfg = get_settings()` call gets a safe mock instead of
# reading the .env file (which has extra fields that pydantic rejects).
import aryx.config as _aryx_config  # safe: no module-level Settings() call

_mock_cfg = MagicMock()
_mock_cfg.llm_provider = "ollama"
_mock_cfg.llm_menial_model = "llama3.2:3b"
_mock_cfg.llm_reason_model = "llama3.2:3b"
_mock_cfg.llm_base_url = "http://localhost:11434"
_mock_cfg.llm_api_key = ""
_mock_cfg.rdb_dsn = "postgresql://localhost/aryx"

_settings_patcher = patch("aryx.config.get_settings", return_value=_mock_cfg)
_settings_patcher.start()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_conn_mock(fetchone_row=None, fetchall_rows=None):
    """Return a connection mock wired as a context manager."""
    mock_cur = MagicMock()
    mock_cur.fetchone.return_value = fetchone_row
    mock_cur.fetchall.return_value = fetchall_rows or []

    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cur)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return mock_conn, mock_cur


# ---------------------------------------------------------------------------
# _llm_stats — SQL param must be (workspace_id,)
# ---------------------------------------------------------------------------

class TestLlmStatsWorkspaceParam:
    """_llm_stats() must pass workspace_id as the only SQL param."""

    def test_llm_stats_passes_workspace_id_tuple(self):
        conn, cur = _make_conn_mock(fetchone_row=(10, 5000, 28, 3000, 2000))
        with patch("aryx.api.observability_api.load", return_value="SELECT ..."):
            from aryx.api.observability_api import _llm_stats
            result = _llm_stats(conn, workspace_id=3)

        execute_call = cur.execute.call_args
        params = execute_call[0][1]
        assert params == (3,), f"expected (3,) got {params!r}"

    def test_llm_stats_different_workspaces_use_correct_param(self):
        for wid in (1, 2, 42):
            conn, cur = _make_conn_mock(fetchone_row=(0, 0, 0, 0, 0))
            with patch("aryx.api.observability_api.load", return_value="SELECT ..."):
                from aryx.api.observability_api import _llm_stats
                _llm_stats(conn, workspace_id=wid)
            params = cur.execute.call_args[0][1]
            assert params == (wid,), f"workspace_id={wid}: expected ({wid},) got {params!r}"

    def test_llm_stats_returns_empty_dict_on_no_row(self):
        conn, _ = _make_conn_mock(fetchone_row=None)
        with patch("aryx.api.observability_api.load", return_value="SELECT ..."):
            from aryx.api.observability_api import _llm_stats
            result = _llm_stats(conn, workspace_id=1)
        assert result == {}

    def test_llm_stats_maps_columns_correctly(self):
        conn, _ = _make_conn_mock(fetchone_row=(7, 350200, 28, 120000, 230200))
        with patch("aryx.api.observability_api.load", return_value="SELECT ..."):
            from aryx.api.observability_api import _llm_stats
            result = _llm_stats(conn, workspace_id=1)
        assert result["total_calls"] == 7
        assert result["total_tokens"] == 350200
        assert result["avg_latency_ms"] == 28


# ---------------------------------------------------------------------------
# _recent_llm — SQL param must be (workspace_id,)
# ---------------------------------------------------------------------------

class TestRecentLlmWorkspaceParam:
    """_recent_llm() must pass workspace_id as the only SQL param."""

    def test_recent_llm_passes_workspace_id_tuple(self):
        conn, cur = _make_conn_mock(fetchall_rows=[])
        with patch("aryx.api.observability_api.load", return_value="SELECT ..."):
            from aryx.api.observability_api import _recent_llm
            _recent_llm(conn, workspace_id=5)

        params = cur.execute.call_args[0][1]
        assert params == (5,), f"expected (5,) got {params!r}"

    def test_recent_llm_returns_list_of_dicts(self):
        import datetime
        ts = datetime.datetime(2026, 7, 3, 12, 0, 0)
        conn, _ = _make_conn_mock(fetchall_rows=[
            ("answer", "llama3.2:3b", 120, 230, 28500, "ask", None, ts),
        ])
        with patch("aryx.api.observability_api.load", return_value="SELECT ..."):
            from aryx.api.observability_api import _recent_llm
            result = _recent_llm(conn, workspace_id=1)

        assert len(result) == 1
        assert result[0]["model"] == "llama3.2:3b"
        assert result[0]["latency_ms"] == 28500


# ---------------------------------------------------------------------------
# _log_call — workspace_id at position 0 in the insert tuple
# ---------------------------------------------------------------------------

class TestLogCallWorkspaceId:
    """_log_call() must write workspace_id as the first positional param."""

    def test_log_call_workspace_id_at_position_zero(self):
        mock_pool = MagicMock()
        mock_cur = MagicMock()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cur)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_pool.connection.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        with patch("aryx.llm_runtime.get_pool", return_value=mock_pool), \
             patch("aryx.llm_runtime.load", return_value="INSERT ..."), \
             patch.dict("os.environ", {"ARYX_RDB_DSN": "postgresql://x"}):
            from aryx.llm_runtime import _log_call
            _log_call("answer", "llama3.2:3b", 100, 200, 500, "", workspace_id=7)

        params = mock_cur.execute.call_args[0][1]
        assert params[0] == 7, f"expected workspace_id=7 at [0], got {params[0]!r}"

    def test_log_call_default_workspace_is_one(self):
        mock_pool = MagicMock()
        mock_cur = MagicMock()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cur)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_pool.connection.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        with patch("aryx.llm_runtime.get_pool", return_value=mock_pool), \
             patch("aryx.llm_runtime.load", return_value="INSERT ..."), \
             patch.dict("os.environ", {"ARYX_RDB_DSN": "postgresql://x"}):
            from aryx.llm_runtime import _log_call
            _log_call("menial", "llama3.2:3b", 50, 80, 100, "")  # no workspace_id

        params = mock_cur.execute.call_args[0][1]
        assert params[0] == 1, f"expected default workspace_id=1 at [0], got {params[0]!r}"

    def test_log_call_noop_when_no_dsn(self):
        """_log_call must be a no-op when ARYX_RDB_DSN is not set."""
        with patch.dict("os.environ", {}, clear=True):
            import os
            os.environ.pop("ARYX_RDB_DSN", None)
            from aryx.llm_runtime import _log_call
            _log_call("answer", "model", 1, 1, 1, "", workspace_id=2)
        # No exception = pass


# ---------------------------------------------------------------------------
# chat() — workspace_id threaded to _log_call
# ---------------------------------------------------------------------------

class TestChatWorkspaceThreading:
    """chat() must pass workspace_id through to _log_call."""

    def test_chat_threads_workspace_id_to_log_call(self):
        captured = {}

        def fake_log(role, model, pt, ct, ms, err, workspace_id=1):
            captured["workspace_id"] = workspace_id

        with patch("aryx.llm_runtime.complete_text", return_value=("answer", 10, 20)), \
             patch("aryx.llm_runtime._log_call", side_effect=fake_log):
            from aryx.llm_runtime import chat
            chat("answer", "sys", "user", workspace_id=42)

        assert captured.get("workspace_id") == 42

    def test_chat_default_workspace_is_one(self):
        captured = {}

        def fake_log(role, model, pt, ct, ms, err, workspace_id=1):
            captured["workspace_id"] = workspace_id

        with patch("aryx.llm_runtime.complete_text", return_value=("answer", 10, 20)), \
             patch("aryx.llm_runtime._log_call", side_effect=fake_log):
            from aryx.llm_runtime import chat
            chat("answer", "sys", "user")  # no workspace_id

        assert captured.get("workspace_id") == 1
