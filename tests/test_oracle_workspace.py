"""Unit tests for oracle_workspace.py — no live Oracle DB required.

All oracledb and psycopg calls are stubbed so these tests run in CI without
an ADB wallet. Covers: module-level SQL constants, CRUD methods, guard logic,
purge/nuke operations, and the f-string-free SQL construction pattern.
"""
from __future__ import annotations

import json
import sys
import types
import unittest
from unittest.mock import MagicMock, patch


# ── Stubs (mirrors test_oracle_pool.py) ──────────────────────────────────────

def _stub_oracledb() -> None:
    if "oracledb" in sys.modules:
        return
    mod = types.ModuleType("oracledb")
    mod.STRING = "STRING"

    class _IntegrityError(Exception):
        pass

    class _Error(Exception):
        pass

    mod.IntegrityError = _IntegrityError
    mod.Error = _Error
    mod.create_pool = MagicMock()
    sys.modules["oracledb"] = mod


def _stub_psycopg() -> None:
    if "psycopg" in sys.modules:
        return
    psycopg = types.ModuleType("psycopg")
    psycopg.connect = MagicMock()
    psycopg.Connection = MagicMock()
    psycopg.Cursor = MagicMock()
    psycopg_sql = types.ModuleType("psycopg.sql")
    psycopg_sql.SQL = MagicMock()
    psycopg_sql.Identifier = MagicMock()
    psycopg.sql = psycopg_sql
    psycopg_types = types.ModuleType("psycopg.types")
    psycopg_types_json = types.ModuleType("psycopg.types.json")
    psycopg_types_json.Json = MagicMock()
    psycopg_types.json = psycopg_types_json
    psycopg.types = psycopg_types
    sys.modules.update({
        "psycopg": psycopg, "psycopg.sql": psycopg_sql,
        "psycopg.types": psycopg_types, "psycopg.types.json": psycopg_types_json,
    })
    psycopg_pool = types.ModuleType("psycopg_pool")
    psycopg_pool.ConnectionPool = MagicMock()
    sys.modules["psycopg_pool"] = psycopg_pool


_stub_psycopg()
_stub_oracledb()

from aryx.store.oracle_workspace import (  # noqa: E402
    OracleWorkspaceStore,
    _DELETE_PARTITION_SQLS,
    _PARTITIONED,
    _TRUNCATE_SQLS,
)


# ── SQL stubs — substitute for real .sql files during testing ─────────────────

_SQL_STUBS: dict[str, str] = {
    "insert_workspace": (
        "INSERT INTO aryx_workspace (name, description, context, brief) "
        "VALUES (%s, %s, %s, %s) RETURNING id, name, description, context, brief, created_at"
    ),
    "select_workspaces": (
        "SELECT id, name, description, context, brief, created_at "
        "FROM aryx_workspace ORDER BY id"
    ),
    "select_workspace_by_id": (
        "SELECT id, name, description, context, brief, created_at "
        "FROM aryx_workspace WHERE id = %s"
    ),
    "update_workspace_context": (
        "UPDATE aryx_workspace SET context = %s WHERE id = %s "
        "RETURNING id, name, description, context, created_at"
    ),
    "update_workspace_brief": (
        "UPDATE aryx_workspace SET brief = %s WHERE id = %s "
        "RETURNING id, name, description, context, brief, created_at"
    ),
    "select_workspace_survivorship": (
        "SELECT survivorship FROM aryx_workspace WHERE id = %s"
    ),
    "update_workspace_survivorship": (
        "UPDATE aryx_workspace SET survivorship = %s WHERE id = %s "
        "RETURNING id, survivorship"
    ),
    # Two semicolon-separated statements so purge_data split logic is exercised.
    "purge_workspace_data": (
        "DELETE FROM aryx_chunk WHERE workspace_id = %(wid)s;\n"
        "DELETE FROM aryx_chunk_embedding WHERE workspace_id = %(wid)s"
    ),
    "nuke_system": "DELETE FROM aryx_llm_call WHERE 1=1",
    "select_non_default_workspace_ids": (
        "SELECT id FROM aryx_workspace WHERE name != 'Default'"
    ),
    "delete_non_default_workspaces": (
        "DELETE FROM aryx_workspace WHERE name != 'Default'"
    ),
    # reset_workspace_context.sql uses %(wid)s which _translate_sql rewrites to
    # :wid on the real OracleCursorWrapper. The mock cursor receives the raw SQL,
    # so use :wid here to keep it Oracle-style and avoid spurious %(wid)s hits.
    "reset_workspace_context": (
        "UPDATE aryx_workspace SET context = ' ' WHERE id = :wid"
    ),
    "delete_profiles_by_workspace": (
        "DELETE FROM aryx_field_profile WHERE workspace_id = %s"
    ),
    "delete_tags_by_workspace": "DELETE FROM aryx_field_tag WHERE workspace_id = %s",
    "delete_runs_by_workspace": "DELETE FROM aryx_run WHERE workspace_id = %s",
    "delete_jobs_by_workspace": "DELETE FROM aryx_job WHERE workspace_id = %s",
    "delete_workspace_row": "DELETE FROM aryx_workspace WHERE id = %s",
}


def _mock_load(name: str) -> str:
    return _SQL_STUBS.get(name, f"SELECT 1 FROM dual -- {name}")


# ── Mock factory ──────────────────────────────────────────────────────────────

def _make_pool_cursor(
    fetchone: tuple | None = None,
    fetchall: list | None = None,
) -> tuple[MagicMock, MagicMock]:
    """Return (pool, cursor) backed by MagicMock context managers.

    All pool.connection() calls return the same conn; all conn.cursor() calls
    return the same cur — sufficient for unit tests that check call args.
    """
    cur = MagicMock()
    cur.fetchone.return_value = fetchone
    cur.fetchall.return_value = fetchall if fetchall is not None else []

    cur_cm = MagicMock()
    cur_cm.__enter__ = MagicMock(return_value=cur)
    cur_cm.__exit__ = MagicMock(return_value=False)

    conn = MagicMock()
    conn.cursor = MagicMock(return_value=cur_cm)

    conn_cm = MagicMock()
    conn_cm.__enter__ = MagicMock(return_value=conn)
    conn_cm.__exit__ = MagicMock(return_value=False)

    pool = MagicMock()
    pool.connection = MagicMock(return_value=conn_cm)

    return pool, cur


def _make_store(pool: MagicMock) -> OracleWorkspaceStore:
    with patch("aryx.store.oracle_workspace.get_oracle_pool", return_value=pool):
        return OracleWorkspaceStore("tcps://test:1522/db")


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestModuleLevelConstants(unittest.TestCase):
    """Pre-built SQL dicts contain the right tables and no f-strings at execute() sites."""

    def test_partitioned_has_four_tables(self) -> None:
        self.assertEqual(len(_PARTITIONED), 4)

    def test_delete_partition_sqls_covers_all_tables(self) -> None:
        for table in _PARTITIONED:
            self.assertIn(table, _DELETE_PARTITION_SQLS,
                          f"{table} missing from _DELETE_PARTITION_SQLS")

    def test_truncate_sqls_covers_all_tables(self) -> None:
        for table in _PARTITIONED:
            self.assertIn(table, _TRUNCATE_SQLS,
                          f"{table} missing from _TRUNCATE_SQLS")

    def test_delete_partition_sql_has_workspace_id_filter(self) -> None:
        for table, sql in _DELETE_PARTITION_SQLS.items():
            self.assertIn("workspace_id", sql,
                          f"_DELETE_PARTITION_SQLS['{table}'] missing workspace_id filter")

    def test_truncate_sql_has_no_where_clause(self) -> None:
        for table, sql in _TRUNCATE_SQLS.items():
            self.assertNotIn("WHERE", sql.upper(),
                             f"_TRUNCATE_SQLS['{table}'] has unexpected WHERE clause")

    def test_delete_partition_sql_references_correct_table(self) -> None:
        for table, sql in _DELETE_PARTITION_SQLS.items():
            self.assertIn(table, sql,
                          f"_DELETE_PARTITION_SQLS entry for '{table}' does not name it")


class TestDropPartitions(unittest.TestCase):
    """_drop_partitions() executes the pre-built SQL for all four tables."""

    def test_executes_for_all_four_partitioned_tables(self) -> None:
        pool, cur = _make_pool_cursor()
        store = _make_store(pool)
        with patch("aryx.store.oracle_workspace.load", side_effect=_mock_load):
            store._drop_partitions(42)
        executed_sqls = [c[0][0] for c in cur.execute.call_args_list]
        for table in _PARTITIONED:
            self.assertIn(_DELETE_PARTITION_SQLS[table], executed_sqls,
                          f"_DELETE_PARTITION_SQLS['{table}'] not executed")

    def test_passes_workspace_id_as_positional_param(self) -> None:
        pool, cur = _make_pool_cursor()
        store = _make_store(pool)
        with patch("aryx.store.oracle_workspace.load", side_effect=_mock_load):
            store._drop_partitions(99)
        for c in cur.execute.call_args_list:
            self.assertEqual(c[0][1], (99,),
                             "Expected workspace_id=99 as positional tuple param")


class TestCreate(unittest.TestCase):
    """create() inserts a workspace and returns a correctly shaped dict."""

    def test_returns_dict_with_all_required_fields(self) -> None:
        row = (7, "My WS", "desc", "ctx", {"domain": "test"}, "2024-01-01")
        pool, cur = _make_pool_cursor(fetchone=row)
        store = _make_store(pool)
        with patch("aryx.store.oracle_workspace.load", side_effect=_mock_load):
            result = store.create("My WS", "desc", "ctx", {"domain": "test"})
        self.assertEqual(result["id"], 7)
        self.assertEqual(result["name"], "My WS")
        self.assertEqual(result["description"], "desc")
        self.assertEqual(result["context"], "ctx")
        self.assertEqual(result["brief"], {"domain": "test"})

    def test_brief_defaults_to_empty_dict_when_none(self) -> None:
        row = (1, "WS", "", "", None, "2024-01-01")
        pool, cur = _make_pool_cursor(fetchone=row)
        store = _make_store(pool)
        with patch("aryx.store.oracle_workspace.load", side_effect=_mock_load):
            result = store.create("WS")
        self.assertEqual(result["brief"], {})

    def test_brief_json_serialized_in_execute_params(self) -> None:
        row = (1, "WS", "", "", {}, "2024-01-01")
        pool, cur = _make_pool_cursor(fetchone=row)
        store = _make_store(pool)
        brief_input = {"domain": "IT", "roles": ["admin", "analyst"]}
        with patch("aryx.store.oracle_workspace.load", side_effect=_mock_load):
            store.create("WS", brief=brief_input)
        _, params = cur.execute.call_args[0]
        self.assertEqual(json.loads(params[3]), brief_input)


class TestListAll(unittest.TestCase):
    """list_all() returns all workspace rows as correctly mapped dicts."""

    def test_returns_empty_list_when_no_rows(self) -> None:
        pool, _ = _make_pool_cursor(fetchall=[])
        store = _make_store(pool)
        with patch("aryx.store.oracle_workspace.load", side_effect=_mock_load):
            result = store.list_all()
        self.assertEqual(result, [])

    def test_maps_rows_to_dicts_with_correct_keys(self) -> None:
        rows = [
            (1, "Default", "", "", {"aim": "test"}, "2024-01-01"),
            (2, "Workspace B", "desc", "ctx", None, "2024-01-02"),
        ]
        pool, _ = _make_pool_cursor(fetchall=rows)
        store = _make_store(pool)
        with patch("aryx.store.oracle_workspace.load", side_effect=_mock_load):
            result = store.list_all()
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["name"], "Default")
        self.assertEqual(result[0]["brief"], {"aim": "test"})
        self.assertEqual(result[1]["name"], "Workspace B")

    def test_brief_is_empty_dict_when_null(self) -> None:
        pool, _ = _make_pool_cursor(fetchall=[(2, "WS", "", "", None, "2024-01-01")])
        store = _make_store(pool)
        with patch("aryx.store.oracle_workspace.load", side_effect=_mock_load):
            result = store.list_all()
        self.assertEqual(result[0]["brief"], {})


class TestGet(unittest.TestCase):
    """get() returns a single workspace row without scanning the full table."""

    def test_returns_workspace_dict_when_row_exists(self) -> None:
        row = (2, "WS", "desc", "ctx", {"domain": "support"}, "2024-01-01")
        pool, _ = _make_pool_cursor(fetchone=row)
        store = _make_store(pool)
        with patch("aryx.store.oracle_workspace.load", side_effect=_mock_load):
            result = store.get(2)
        self.assertEqual(result, {
            "id": 2,
            "name": "WS",
            "description": "desc",
            "context": "ctx",
            "brief": {"domain": "support"},
            "created_at": "2024-01-01",
        })

    def test_returns_none_when_workspace_missing(self) -> None:
        pool, _ = _make_pool_cursor(fetchone=None)
        store = _make_store(pool)
        with patch("aryx.store.oracle_workspace.load", side_effect=_mock_load):
            result = store.get(9)
        self.assertIsNone(result)


class TestSetContext(unittest.TestCase):
    """set_context() updates the context field."""

    def test_returns_dict_with_updated_context(self) -> None:
        row = (1, "WS", "desc", "new ctx", "2024-01-01")
        pool, _ = _make_pool_cursor(fetchone=row)
        store = _make_store(pool)
        with patch("aryx.store.oracle_workspace.load", side_effect=_mock_load):
            result = store.set_context(1, "new ctx")
        self.assertEqual(result["context"], "new ctx")
        self.assertIn("id", result)

    def test_brief_is_empty_dict(self) -> None:
        # set_context returns brief: {} — update_workspace_context SQL does not
        # select the brief column (5 columns, not 6).
        row = (1, "WS", "", "ctx", "2024-01-01")
        pool, _ = _make_pool_cursor(fetchone=row)
        store = _make_store(pool)
        with patch("aryx.store.oracle_workspace.load", side_effect=_mock_load):
            result = store.set_context(1, "ctx")
        self.assertEqual(result["brief"], {})


class TestSetBrief(unittest.TestCase):
    """set_brief() persists the brief JSON and returns the updated workspace."""

    def test_brief_json_serialized_before_execute(self) -> None:
        brief = {"domain": "HR", "aim": "match employees"}
        row = (1, "WS", "", "", brief, "2024-01-01")
        pool, cur = _make_pool_cursor(fetchone=row)
        store = _make_store(pool)
        with patch("aryx.store.oracle_workspace.load", side_effect=_mock_load):
            store.set_brief(1, brief)
        _, params = cur.execute.call_args[0]
        self.assertEqual(json.loads(params[0]), brief)

    def test_returns_brief_from_db_row(self) -> None:
        saved = {"domain": "HR", "aim": "test"}
        row = (1, "WS", "", "", saved, "2024-01-01")
        pool, _ = _make_pool_cursor(fetchone=row)
        store = _make_store(pool)
        with patch("aryx.store.oracle_workspace.load", side_effect=_mock_load):
            result = store.set_brief(1, saved)
        self.assertEqual(result["brief"], saved)

    def test_empty_brief_stored_as_empty_json_object(self) -> None:
        row = (1, "WS", "", "", {}, "2024-01-01")
        pool, cur = _make_pool_cursor(fetchone=row)
        store = _make_store(pool)
        with patch("aryx.store.oracle_workspace.load", side_effect=_mock_load):
            store.set_brief(1, {})
        _, params = cur.execute.call_args[0]
        self.assertEqual(json.loads(params[0]), {})


class TestGetSurvivorship(unittest.TestCase):
    """get_survivorship() returns the policy dict or {} when null."""

    def test_returns_policy_when_row_present(self) -> None:
        policy = {"strategy": "source_priority", "sources": ["crm"]}
        pool, _ = _make_pool_cursor(fetchone=(policy,))
        store = _make_store(pool)
        with patch("aryx.store.oracle_workspace.load", side_effect=_mock_load):
            result = store.get_survivorship(1)
        self.assertEqual(result, policy)

    def test_returns_empty_dict_when_no_row(self) -> None:
        pool, _ = _make_pool_cursor(fetchone=None)
        store = _make_store(pool)
        with patch("aryx.store.oracle_workspace.load", side_effect=_mock_load):
            result = store.get_survivorship(1)
        self.assertEqual(result, {})


class TestDelete(unittest.TestCase):
    """delete() enforces the default-workspace guard and cleans up all data."""

    def test_raises_for_default_workspace_id_1(self) -> None:
        pool, _ = _make_pool_cursor()
        store = _make_store(pool)
        with self.assertRaises(ValueError):
            store.delete(1)

    def test_executes_delete_workspace_row_for_non_default(self) -> None:
        pool, cur = _make_pool_cursor()
        store = _make_store(pool)
        with patch("aryx.store.oracle_workspace.load", side_effect=_mock_load):
            store.delete(5)
        executed_sqls = [c[0][0] for c in cur.execute.call_args_list]
        expected = _SQL_STUBS["delete_workspace_row"]
        self.assertIn(expected, executed_sqls,
                      "delete_workspace_row SQL not found in execute calls")

    def test_drop_partitions_called_before_row_delete(self) -> None:
        pool, cur = _make_pool_cursor()
        store = _make_store(pool)
        with patch("aryx.store.oracle_workspace.load", side_effect=_mock_load):
            store.delete(5)
        # _drop_partitions must be called: its SQL appears before the row delete
        executed_sqls = [c[0][0] for c in cur.execute.call_args_list]
        partition_sqls = list(_DELETE_PARTITION_SQLS.values())
        self.assertTrue(
            any(sql in executed_sqls for sql in partition_sqls),
            "_drop_partitions SQL not found — partition rows not cleaned up",
        )


class TestNuke(unittest.TestCase):
    """nuke() issues a factory reset using pre-built _TRUNCATE_SQLS."""

    def test_uses_truncate_sqls_for_all_partitioned_tables(self) -> None:
        pool, cur = _make_pool_cursor(fetchall=[])  # no non-default workspaces
        store = _make_store(pool)
        with patch("aryx.store.oracle_workspace.load", side_effect=_mock_load):
            store.nuke()
        executed_sqls = [c[0][0] for c in cur.execute.call_args_list]
        for table in _PARTITIONED:
            self.assertIn(
                _TRUNCATE_SQLS[table], executed_sqls,
                f"_TRUNCATE_SQLS['{table}'] not found in nuke execute calls",
            )

    def test_returns_status_nuked(self) -> None:
        pool, _ = _make_pool_cursor(fetchall=[])
        store = _make_store(pool)
        with patch("aryx.store.oracle_workspace.load", side_effect=_mock_load):
            result = store.nuke()
        self.assertEqual(result["status"], "nuked")

    def test_workspaces_removed_reflects_fetchall_count(self) -> None:
        # One non-default workspace exists → removed count = 1
        pool, cur = _make_pool_cursor(fetchall=[(2,)])
        store = _make_store(pool)
        with patch("aryx.store.oracle_workspace.load", side_effect=_mock_load):
            result = store.nuke()
        self.assertEqual(result["workspaces_removed"], 1)


class TestPurgeData(unittest.TestCase):
    """purge_data() clears workspace data and replaces %(wid)s params."""

    def test_replaces_named_param_in_purge_sql(self) -> None:
        pool, cur = _make_pool_cursor()
        store = _make_store(pool)
        with patch("aryx.store.oracle_workspace.load", side_effect=_mock_load):
            store.purge_data(3)
        executed_sqls = [str(c[0][0]) for c in cur.execute.call_args_list]
        self.assertFalse(
            any("%(wid)s" in sql for sql in executed_sqls),
            "%(wid)s was not replaced before execute() — oracle param style broken",
        )

    def test_wid_param_bound_as_dict(self) -> None:
        pool, cur = _make_pool_cursor()
        store = _make_store(pool)
        with patch("aryx.store.oracle_workspace.load", side_effect=_mock_load):
            store.purge_data(7)
        # At least one execute call should pass {"wid": 7}
        dict_params = [
            c[0][1] for c in cur.execute.call_args_list
            if len(c[0]) > 1 and isinstance(c[0][1], dict)
        ]
        self.assertTrue(
            any(p.get("wid") == 7 for p in dict_params),
            "wid=7 not found in any dict param passed to execute()",
        )

    def test_returns_status_purged(self) -> None:
        pool, _ = _make_pool_cursor()
        store = _make_store(pool)
        with patch("aryx.store.oracle_workspace.load", side_effect=_mock_load):
            result = store.purge_data(3)
        self.assertEqual(result["status"], "purged")
        self.assertEqual(result["workspace_id"], 3)


class TestClose(unittest.TestCase):
    """close() is a no-op — the pool manages its own lifecycle."""

    def test_close_does_not_raise(self) -> None:
        pool, _ = _make_pool_cursor()
        store = _make_store(pool)
        store.close()  # must not raise


if __name__ == "__main__":
    unittest.main()
