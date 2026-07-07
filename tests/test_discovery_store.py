"""Unit tests for DiscoveryStore — stubbed pool, no live DB."""
from __future__ import annotations

import json
import sys
import types
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ── Stub heavy DB dependencies before any aryx import ────────────────────────

def _stub_psycopg() -> None:
    if "psycopg" in sys.modules:
        return
    psycopg = types.ModuleType("psycopg")
    psycopg.connect = MagicMock()
    sys.modules["psycopg"] = psycopg
    # psycopg.types.json.Json
    psycopg_types = types.ModuleType("psycopg.types")
    psycopg_json = types.ModuleType("psycopg.types.json")
    psycopg_json.Json = MagicMock()
    psycopg_types.json = psycopg_json
    sys.modules["psycopg.types"] = psycopg_types
    sys.modules["psycopg.types.json"] = psycopg_json
    # psycopg_pool.ConnectionPool
    pool_mod = types.ModuleType("psycopg_pool")
    pool_mod.ConnectionPool = MagicMock()
    sys.modules["psycopg_pool"] = pool_mod
    # falkordb
    falkor = types.ModuleType("falkordb")
    falkor.FalkorDB = MagicMock()
    sys.modules["falkordb"] = falkor


_stub_psycopg()

from aryx.store.discovery_store import DiscoveryStore  # noqa: E402

_DSN = "postgresql://test"
_DID = "abc123"
_WS = 1


_PATCHES: list[Any] = []


def setup_module(module: Any) -> None:
    """Patch load and get_pool at module level for the duration of the test run."""
    p1 = patch("aryx.store.discovery_store.load", return_value="SELECT 1")
    p2 = patch("aryx.store.pool.get_pool")
    _PATCHES.extend([p1.start(), p2.start()])


def teardown_module(module: Any) -> None:
    patch.stopall()


def _make_store() -> tuple[DiscoveryStore, MagicMock]:
    """Return (store, mock_pool). get_pool already patched by setup_module."""
    mock_pool = MagicMock()
    with patch("aryx.store.discovery_store.get_pool", return_value=mock_pool):
        store = DiscoveryStore(_DSN)
    return store, mock_pool


def _cursor_returning(rows: list[tuple] | tuple | None) -> MagicMock:
    """Fake cursor whose fetchone/fetchall return the given rows."""
    cur = MagicMock()
    if isinstance(rows, list):
        cur.fetchall.return_value = rows
        cur.fetchone.return_value = rows[0] if rows else None
    else:
        cur.fetchone.return_value = rows
        cur.fetchall.return_value = [rows] if rows else []
    return cur


def _conn_with_cursor(cursor: MagicMock) -> MagicMock:
    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return conn


def _pool_with_conn(conn: MagicMock) -> MagicMock:
    pool = MagicMock()
    pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
    pool.connection.return_value.__exit__ = MagicMock(return_value=False)
    return pool


# ── Core behaviour ───────────────────────────────────────────────────────────

def test_put_and_get_returns_row() -> None:
    store, mock_pool = _make_store()
    row = (_DID, _WS, "pending", '{"k": 1}', '{"types": []}', 1,
           '{}', datetime.now(tz=timezone.utc), None)
    cur = _cursor_returning(row)
    conn = _conn_with_cursor(cur)
    mock_pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
    mock_pool.connection.return_value.__exit__ = MagicMock(return_value=False)

    result = store.get(_DID, _WS)
    assert result is not None
    assert result["discovery_id"] == _DID
    assert result["data"] == {"k": 1}


def test_get_wrong_workspace_returns_none() -> None:
    store, mock_pool = _make_store()
    cur = _cursor_returning(None)
    conn = _conn_with_cursor(cur)
    mock_pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
    mock_pool.connection.return_value.__exit__ = MagicMock(return_value=False)

    result = store.get(_DID, workspace_id=2)
    assert result is None


def test_get_unknown_id_returns_none() -> None:
    store, mock_pool = _make_store()
    cur = _cursor_returning(None)
    conn = _conn_with_cursor(cur)
    mock_pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
    mock_pool.connection.return_value.__exit__ = MagicMock(return_value=False)

    result = store.get("nonexistent", _WS)
    assert result is None


def test_put_upsert_is_idempotent() -> None:
    """put() must call execute exactly once — upsert handles conflict in DB."""
    store, mock_pool = _make_store()
    cur = MagicMock()
    conn = _conn_with_cursor(cur)
    mock_pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
    mock_pool.connection.return_value.__exit__ = MagicMock(return_value=False)

    store.put(_DID, _WS, {"k": 1}, {"types": []}, 1)
    store.put(_DID, _WS, {"k": 2}, {"types": []}, 1)
    assert cur.execute.call_count == 2


def test_mark_confirmed_sets_status() -> None:
    store, mock_pool = _make_store()
    cur = MagicMock()
    conn = _conn_with_cursor(cur)
    mock_pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
    mock_pool.connection.return_value.__exit__ = MagicMock(return_value=False)

    store.mark_confirmed(_DID, "job001")
    cur.execute.assert_called_once()
    call_args = cur.execute.call_args[0]
    assert _DID in call_args[1]


def test_update_confirm_state_persists_json() -> None:
    store, mock_pool = _make_store()
    cur = MagicMock()
    conn = _conn_with_cursor(cur)
    mock_pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
    mock_pool.connection.return_value.__exit__ = MagicMock(return_value=False)

    state = {"completed_plans": ["a.csv"], "plan_run_ids": {"a.csv": "r1"}}
    store.update_confirm_state(_DID, state)
    cur.execute.assert_called_once()
    call_args = cur.execute.call_args[0]
    # First positional param should be JSON-serialised state
    assert json.loads(call_args[1][0]) == state


# ── pending_days logic ───────────────────────────────────────────────────────

def _list_row(status: str, created_at: datetime, confirmed_at=None):
    return ("did1", status, '{"types": []}', 5, created_at, confirmed_at)


def test_list_recent_pending_days_computed_for_pending() -> None:
    store, mock_pool = _make_store()
    created = datetime.now(tz=timezone.utc) - timedelta(days=9)
    cur = _cursor_returning([_list_row("pending", created)])
    conn = _conn_with_cursor(cur)
    mock_pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
    mock_pool.connection.return_value.__exit__ = MagicMock(return_value=False)

    result = store.list_recent(_WS)
    assert len(result) == 1
    assert result[0]["pending_days"] == 9


def test_list_recent_pending_days_none_for_partial() -> None:
    store, mock_pool = _make_store()
    created = datetime.now(tz=timezone.utc) - timedelta(days=9)
    cur = _cursor_returning([_list_row("partial", created)])
    conn = _conn_with_cursor(cur)
    mock_pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
    mock_pool.connection.return_value.__exit__ = MagicMock(return_value=False)

    result = store.list_recent(_WS)
    assert result[0]["pending_days"] is None


def test_list_recent_pending_days_none_for_confirmed() -> None:
    store, mock_pool = _make_store()
    created = datetime.now(tz=timezone.utc) - timedelta(days=9)
    confirmed = datetime.now(tz=timezone.utc)
    cur = _cursor_returning([_list_row("confirmed", created, confirmed)])
    conn = _conn_with_cursor(cur)
    mock_pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
    mock_pool.connection.return_value.__exit__ = MagicMock(return_value=False)

    result = store.list_recent(_WS)
    assert result[0]["pending_days"] is None


def test_list_recent_pending_days_below_threshold() -> None:
    """pending_days is returned as-is; UI decides whether to show the warning."""
    store, mock_pool = _make_store()
    created = datetime.now(tz=timezone.utc) - timedelta(days=3)
    cur = _cursor_returning([_list_row("pending", created)])
    conn = _conn_with_cursor(cur)
    mock_pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
    mock_pool.connection.return_value.__exit__ = MagicMock(return_value=False)

    result = store.list_recent(_WS)
    assert result[0]["pending_days"] == 3


def test_close_is_noop() -> None:
    store, _ = _make_store()
    store.close()  # must not raise
