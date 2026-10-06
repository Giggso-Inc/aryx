"""Unit tests for app/core/oracle_client.py -- the thick-mode init shay-api
runs explicitly from main.py before any DB connection. See docs/oci-oracle/
ORACLE_THICK_MODE_MIGRATION_PLAN_2026-10-06.md ("shay-api" section).

Unlike aryx's src/aryx/api/main_oracle_client.py, this module does not call
init_thick_mode_if_configured() at import time -- main.py does, explicitly
-- so no module-reload/import-time-guard gymnastics are needed here beyond
resetting the `_initialized` flag between tests.

No real Oracle Instant Client is required: oracledb's pure-Python import
works without Instant Client installed; only actually calling
init_oracle_client() against real libs would need it, and that call is
mocked here.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.core import oracle_client


@pytest.fixture(autouse=True)
def _reset_initialized_guard():
    oracle_client._initialized = False
    yield
    oracle_client._initialized = False


class TestFirstPathEntry:
    def test_none_returns_none(self):
        assert oracle_client._first_path_entry(None) is None

    def test_empty_string_returns_none(self):
        assert oracle_client._first_path_entry("") is None

    def test_single_dir_returned_unchanged(self):
        assert oracle_client._first_path_entry("/opt/oracle/instantclient_23_8") == "/opt/oracle/instantclient_23_8"

    def test_colon_separated_list_returns_first_entry(self):
        """The PR #439 review flagged this: LD_LIBRARY_PATH may be a
        colon-separated list, and init_oracle_client() fails (then falls
        back to thin) if handed the whole string verbatim."""
        assert oracle_client._first_path_entry(
            "/opt/oracle/instantclient_23_8:/usr/lib/other"
        ) == "/opt/oracle/instantclient_23_8"


class TestInitThickModeIfConfigured:
    def test_noop_when_mode_not_thick(self, monkeypatch):
        monkeypatch.delenv("ARYX_ORACLE_CLIENT_MODE", raising=False)
        with patch("oracledb.init_oracle_client") as init_mock:
            oracle_client.init_thick_mode_if_configured()
        init_mock.assert_not_called()

    def test_idempotency_guard_skips_second_call(self, monkeypatch):
        monkeypatch.setenv("ARYX_ORACLE_CLIENT_MODE", "thick")
        with patch("oracledb.init_oracle_client") as init_mock:
            oracle_client.init_thick_mode_if_configured()
            oracle_client.init_thick_mode_if_configured()
        init_mock.assert_called_once()

    def test_success_path_calls_init_oracle_client_with_lib_dir(self, monkeypatch):
        monkeypatch.setenv("ARYX_ORACLE_CLIENT_MODE", "thick")
        monkeypatch.setenv("ARYX_ORACLE_INSTANT_CLIENT_DIR", "/opt/oracle/instantclient_23_8")
        with patch("oracledb.init_oracle_client") as init_mock:
            oracle_client.init_thick_mode_if_configured()
        init_mock.assert_called_once_with(lib_dir="/opt/oracle/instantclient_23_8")

    def test_failure_falls_back_to_thin_without_raising(self, monkeypatch, caplog):
        """Best-effort by design, same as api's equivalent module: a broken
        Instant Client install must not crash the process."""
        monkeypatch.setenv("ARYX_ORACLE_CLIENT_MODE", "thick")
        with patch("oracledb.init_oracle_client", side_effect=RuntimeError("DPI-1047: boom")):
            oracle_client.init_thick_mode_if_configured()  # must not raise

        assert any("thick mode init FAILED" in r.message for r in caplog.records)

    def test_colon_separated_ld_library_path_is_split_before_use(self, monkeypatch):
        monkeypatch.setenv("ARYX_ORACLE_CLIENT_MODE", "thick")
        monkeypatch.delenv("ARYX_ORACLE_INSTANT_CLIENT_DIR", raising=False)
        monkeypatch.setenv("LD_LIBRARY_PATH", "/opt/oracle/instantclient_23_8:/usr/lib/other")
        with patch("oracledb.init_oracle_client") as init_mock:
            oracle_client.init_thick_mode_if_configured()
        init_mock.assert_called_once_with(lib_dir="/opt/oracle/instantclient_23_8")
