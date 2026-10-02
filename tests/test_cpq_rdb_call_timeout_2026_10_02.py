"""RDB call timeout (dev-rv-msi #368 Part A + #370 SET half), Postgres and Oracle.

Oracle behaviour is mock-tested only; needs a live ADB check.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from aryx.cpq.rdb.rdb_oracle import OracleCpqRdb
from aryx.cpq.rdb.rdb_postgres import PostgresCpqRdb


def _settings(enabled=True, ms=1234):
    return SimpleNamespace(
        cpq_rdb_call_timeout_enabled=enabled, cpq_rdb_call_timeout_ms=ms,
        effective_dsn=lambda: "dsn", oci_adb_dsn="adb",
    )


class _PgConn:
    def __init__(self, fail_set=False):
        self.executed = []
        self.fail_set = fail_set

    def execute(self, sql, params=()):
        self.executed.append((sql, params))
        if self.fail_set and "DEFAULT" not in sql:
            raise RuntimeError("set failed")


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    @contextmanager
    def connection(self):
        yield self.conn


def _pg(conn, enabled=True):
    with patch("aryx.cpq.rdb.rdb_postgres.get_settings", return_value=_settings(enabled)), \
         patch("aryx.store.pool.get_pool", return_value=_Pool(conn)):
        return PostgresCpqRdb()._connection()


def test_pg_set_is_literal_with_empty_params_and_reset():
    conn = _PgConn()
    with _pg(conn) as c:
        assert c is conn
    assert conn.executed == [
        ("SET statement_timeout = 1234", ()),
        ("SET statement_timeout = DEFAULT", ()),
    ]


def test_pg_reset_in_finally_on_exception():
    conn = _PgConn()
    with pytest.raises(ValueError):
        with _pg(conn):
            raise ValueError("boom")
    assert conn.executed[-1][0] == "SET statement_timeout = DEFAULT"


def test_pg_set_failure_swallowed_with_warning(caplog):
    conn = _PgConn(fail_set=True)
    with caplog.at_level(logging.WARNING):
        with _pg(conn) as c:
            assert c is conn
    assert any("SET statement_timeout failed" in r.message for r in caplog.records)


def test_pg_flag_off_issues_nothing():
    conn = _PgConn()
    with _pg(conn, enabled=False):
        pass
    assert conn.executed == []


class _OraConn:
    def __init__(self, initial=0):
        object.__setattr__(self, "history", [])
        self.call_timeout = initial
        self.history.clear()

    def __setattr__(self, k, v):
        if k == "call_timeout":
            self.history.append(v)
        object.__setattr__(self, k, v)

    def cursor(self):  # must never be used for timeouts
        raise AssertionError("cursor must not be touched")


def _ora(conn, enabled=True):
    with patch("aryx.cpq.rdb.rdb_postgres.get_settings", return_value=_settings(enabled)), \
         patch("aryx.cpq.rdb.rdb_oracle.get_settings", return_value=_settings(enabled)), \
         patch("aryx.store.oracle_pool.get_oracle_pool", return_value=_Pool(conn)):
        return OracleCpqRdb()._connection()


def test_oracle_call_timeout_set_and_restored():
    conn = _OraConn(initial=777)
    with _ora(conn) as c:
        assert c.call_timeout == 1234
    assert conn.call_timeout == 777


def test_oracle_call_timeout_restored_on_exception():
    conn = _OraConn(initial=0)
    with pytest.raises(ValueError):
        with _ora(conn):
            raise ValueError("boom")
    assert conn.call_timeout == 0


def test_oracle_flag_off_touches_nothing():
    conn = _OraConn(initial=5)
    with _ora(conn, enabled=False):
        pass
    assert conn.history == []


def test_timeout_error_logs_warning_when_flag_on(caplog):
    class Boom(PostgresCpqRdb):
        def _connection(self):
            raise RuntimeError("DPY-4024: call timeout of 1234 ms exceeded")

    with patch("aryx.cpq.rdb.rdb_postgres.get_settings", return_value=_settings(True)), \
         caplog.at_level(logging.WARNING):
        assert Boom().fetch_entity_attributes([1], 1) == {}
    assert any("timed out" in r.message for r in caplog.records)


def test_timeout_warning_gated_by_flag(caplog):
    class Boom(PostgresCpqRdb):
        def _connection(self):
            raise RuntimeError("canceling statement due to statement timeout")

    with patch("aryx.cpq.rdb.rdb_postgres.get_settings", return_value=_settings(False)), \
         caplog.at_level(logging.WARNING):
        Boom().fetch_entity_attributes([1], 1)
    assert not caplog.records


def test_non_timeout_error_no_warning(caplog):
    class Boom(PostgresCpqRdb):
        def _connection(self):
            raise RuntimeError("syntax error")

    with patch("aryx.cpq.rdb.rdb_postgres.get_settings", return_value=_settings(True)), \
         caplog.at_level(logging.WARNING):
        Boom().fetch_entity_attributes([1], 1)
    assert not caplog.records
