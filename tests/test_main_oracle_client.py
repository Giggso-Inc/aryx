"""Unit tests for src/aryx/api/main_oracle_client.py -- the thick-mode init
module api runs at import time. See docs/oci-oracle/
ORACLE_THICK_MODE_MIGRATION_PLAN_2026-10-06.md.

The module calls _init_thick_mode_if_configured() once at import time, so
these tests reset its module-level `_initialized` guard and call the
function directly under controlled env vars / a mocked oracledb, rather
than re-importing the module (unreliable across test runs, same rationale
tests/test_database_characterization.py documents for database.py).

No real Oracle Instant Client or raven_log backend is required: oracledb's
pure-Python import works without Instant Client installed (only actually
calling init_oracle_client() against real libs would need it, and that
call is mocked here), and raven_log() is exercised through its own
contract tests elsewhere, not re-verified here.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from aryx.api import main_oracle_client


@pytest.fixture(autouse=True)
def _reset_initialized_guard():
    """Each test gets a clean _initialized=False so the function's real
    logic runs, not the "already initialized, no-op" early return."""
    main_oracle_client._initialized = False
    yield
    main_oracle_client._initialized = False


class TestFirstPathEntry:
    def test_none_returns_none(self):
        assert main_oracle_client._first_path_entry(None) == None  # noqa: E711 -- explicit None check

    def test_empty_string_returns_none(self):
        assert main_oracle_client._first_path_entry("") is None

    def test_single_dir_returned_unchanged(self):
        assert main_oracle_client._first_path_entry("/opt/oracle/instantclient_23_8") == "/opt/oracle/instantclient_23_8"

    def test_colon_separated_list_returns_first_entry(self):
        """The PR #439 review flagged this: LD_LIBRARY_PATH may be a
        colon-separated list, and init_oracle_client() fails (then falls
        back to thin) if handed the whole string verbatim."""
        assert main_oracle_client._first_path_entry(
            "/opt/oracle/instantclient_23_8:/usr/lib/other"
        ) == "/opt/oracle/instantclient_23_8"


class TestInitThickModeIfConfigured:
    def test_noop_when_mode_not_thick(self, monkeypatch):
        monkeypatch.delenv("ARYX_ORACLE_CLIENT_MODE", raising=False)
        with patch("oracledb.init_oracle_client") as init_mock:
            main_oracle_client._init_thick_mode_if_configured()
        init_mock.assert_not_called()

    def test_idempotency_guard_skips_second_call(self, monkeypatch):
        monkeypatch.setenv("ARYX_ORACLE_CLIENT_MODE", "thick")
        with patch("oracledb.init_oracle_client") as init_mock:
            main_oracle_client._init_thick_mode_if_configured()
            main_oracle_client._init_thick_mode_if_configured()
        init_mock.assert_called_once()

    def test_success_path_calls_init_oracle_client_with_lib_dir(self, monkeypatch):
        monkeypatch.setenv("ARYX_ORACLE_CLIENT_MODE", "thick")
        monkeypatch.setenv("ARYX_ORACLE_INSTANT_CLIENT_DIR", "/opt/oracle/instantclient_23_8")
        with patch("oracledb.init_oracle_client") as init_mock, \
             patch("aryx.api.main_oracle_client.raven_log") as raven_log_mock:
            main_oracle_client._init_thick_mode_if_configured()

        init_mock.assert_called_once_with(lib_dir="/opt/oracle/instantclient_23_8")
        raven_log_mock.assert_called_once()
        assert raven_log_mock.call_args.args[0] == "INFO"
        assert raven_log_mock.call_args.kwargs["context"]["result"] == "ok"

    def test_failure_falls_back_to_thin_without_raising(self, monkeypatch):
        """Best-effort by design: a broken Instant Client install must not
        crash the process at import time -- see the module's own docstring."""
        monkeypatch.setenv("ARYX_ORACLE_CLIENT_MODE", "thick")
        with patch("oracledb.init_oracle_client", side_effect=RuntimeError("DPI-1047: boom")), \
             patch("aryx.api.main_oracle_client.raven_log") as raven_log_mock:
            main_oracle_client._init_thick_mode_if_configured()  # must not raise

        raven_log_mock.assert_called_once()
        assert raven_log_mock.call_args.args[0] == "ERROR"
        ctx = raven_log_mock.call_args.kwargs["context"]
        assert ctx["result"] == "failed_fallback_thin"
        assert ctx["error_class"] == "RuntimeError"
        # Dependency evidence class requires these -- PR #439 fixed their
        # absence; this guards against the fields silently disappearing again.
        assert "duration_ms" in ctx
        assert "trace_id" in ctx

    def test_colon_separated_ld_library_path_is_split_before_use(self, monkeypatch):
        monkeypatch.setenv("ARYX_ORACLE_CLIENT_MODE", "thick")
        monkeypatch.delenv("ARYX_ORACLE_INSTANT_CLIENT_DIR", raising=False)
        monkeypatch.setenv("LD_LIBRARY_PATH", "/opt/oracle/instantclient_23_8:/usr/lib/other")
        with patch("oracledb.init_oracle_client") as init_mock, \
             patch("aryx.api.main_oracle_client.raven_log"):
            main_oracle_client._init_thick_mode_if_configured()

        init_mock.assert_called_once_with(lib_dir="/opt/oracle/instantclient_23_8")
