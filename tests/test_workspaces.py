"""Regression tests for WorkspaceStore pooling behavior."""
from __future__ import annotations

import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

store_pkg = types.ModuleType("aryx.store")
store_pkg.__path__ = []
pool_mod = types.ModuleType("aryx.store.pool")
pool_mod.get_pool = MagicMock()
sys.modules.setdefault("aryx.store", store_pkg)
sys.modules.setdefault("aryx.store.pool", pool_mod)


for _mod in ("falkordb", "pgvector", "pgvector.psycopg"):
    sys.modules.setdefault(_mod, MagicMock())

if "psycopg" not in sys.modules:
    psycopg = types.ModuleType("psycopg")
    psycopg.errors = SimpleNamespace(
        UndefinedTable=type("UndefinedTable", (Exception,), {}),
        InFailedSqlTransaction=type("InFailedSqlTransaction", (Exception,), {}),
    )
    psycopg_sql = types.ModuleType("psycopg.sql")
    psycopg_sql.SQL = MagicMock()
    psycopg_sql.Identifier = MagicMock()
    psycopg_sql.Literal = MagicMock()
    psycopg.sql = psycopg_sql
    psycopg_types = types.ModuleType("psycopg.types")
    psycopg_types_json = types.ModuleType("psycopg.types.json")
    psycopg_types_json.Json = lambda value: value
    psycopg_types.json = psycopg_types_json
    psycopg.types = psycopg_types
    sys.modules.update({
        "psycopg": psycopg,
        "psycopg.sql": psycopg_sql,
        "psycopg.types": psycopg_types,
        "psycopg.types.json": psycopg_types_json,
    })

sys.modules.setdefault("psycopg_pool", MagicMock(ConnectionPool=MagicMock()))

import aryx.workspaces as workspaces


def _make_pool() -> tuple[MagicMock, MagicMock]:
    """Return a pool mock whose execute() supports nuke() fetchall calls."""
    conn = MagicMock()

    def _execute(query, params=None):  # noqa: ANN001
        result = MagicMock()
        if query == "select_partition_children":
            result.fetchall.return_value = [("aryx_entity_ws2",)]
        elif query == "select_non_default_workspace_ids":
            result.fetchall.return_value = [(2,), (3,)]
        else:
            result.fetchall.return_value = []
        return result

    conn.execute.side_effect = _execute

    conn_cm = MagicMock()
    conn_cm.__enter__.return_value = conn
    conn_cm.__exit__.return_value = False

    pool = MagicMock()
    pool.connection.return_value = conn_cm
    return pool, conn


def test_nuke_reuses_the_borrowed_connection_for_partition_drops() -> None:
    """nuke() must not re-enter the pool while it already holds a connection."""
    pool, _conn = _make_pool()

    with patch.object(workspaces, "get_pool", return_value=pool), \
         patch.object(workspaces, "load", side_effect=lambda name: name):
        store = workspaces.WorkspaceStore("postgresql://test/db")
        result = store.nuke()

    assert pool.connection.call_count == 1
    assert result == {"status": "nuked", "workspaces_removed": 2}
