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
    _parse_brief,
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

    def test_brief_parsed_when_oracle_returns_json_string(self) -> None:
        """SELECT brief may return a JSON string on the thin client — _parse_brief handles it."""
        brief = {"domain": "Sales", "aim": "Track pipeline"}
        rows = [(1, "WS", "", "", json.dumps(brief), "2024-01-01")]
        pool, _ = _make_pool_cursor(fetchall=rows)
        store = _make_store(pool)
        with patch("aryx.store.oracle_workspace.load", side_effect=_mock_load):
            result = store.list_all()
        self.assertEqual(result[0]["brief"], brief)


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
    """set_brief() persists the brief JSON and returns the updated workspace.

    Oracle-specific concerns tested here:
    - Brief dict is serialised with json.dumps() before the execute() call
      (oracledb thin cannot bind Python dicts directly — DPY-3002).
    - RETURNING clause returns brief as a JSON string via STRING var; _parse_brief()
      must convert it back to a Python dict before the caller sees it.
    - None brief is stored as '{}', not as NULL.
    - Workspace ID is coerced to int.
    """

    _FULL_BRIEF = {
        "domain": "CRM",
        "aim": "Route support tickets to the right agent",
        "objectives": ["improve CSAT", "reduce handle time"],
        "scope": "Inbound support tickets only",
        "roles": ["support agent", "tier-2 specialist"],
    }

    # ── bind-param shape ──────────────────────────────────────────────────────

    def test_brief_json_serialized_before_execute(self) -> None:
        """Dict is json.dumps()'d — oracledb thin cannot bind plain dicts."""
        brief = {"domain": "HR", "aim": "match employees"}
        row = (1, "WS", "", "", brief, "2024-01-01")
        pool, cur = _make_pool_cursor(fetchone=row)
        store = _make_store(pool)
        with patch("aryx.store.oracle_workspace.load", side_effect=_mock_load):
            store.set_brief(1, brief)
        _, params = cur.execute.call_args[0]
        self.assertEqual(json.loads(params[0]), brief)

    def test_workspace_id_is_second_execute_param(self) -> None:
        """execute() params must be (json_string, int_workspace_id)."""
        brief = {"domain": "Sales"}
        row = (5, "WS", "", "", brief, "2024-01-01")
        pool, cur = _make_pool_cursor(fetchone=row)
        store = _make_store(pool)
        with patch("aryx.store.oracle_workspace.load", side_effect=_mock_load):
            store.set_brief(5, brief)
        _, params = cur.execute.call_args[0]
        self.assertEqual(params[1], 5)

    def test_workspace_id_coerced_to_int(self) -> None:
        """set_brief() calls int(wid) so float/numeric wid values work."""
        brief = {"domain": "Finance"}
        row = (3, "WS", "", "", brief, "2024-01-01")
        pool, cur = _make_pool_cursor(fetchone=row)
        store = _make_store(pool)
        with patch("aryx.store.oracle_workspace.load", side_effect=_mock_load):
            store.set_brief(3.0, brief)  # type: ignore[arg-type]
        _, params = cur.execute.call_args[0]
        self.assertIsInstance(params[1], int)
        self.assertEqual(params[1], 3)

    def test_none_brief_stored_as_empty_json_object(self) -> None:
        """None input must be stored as '{}', not as NULL."""
        row = (1, "WS", "", "", {}, "2024-01-01")
        pool, cur = _make_pool_cursor(fetchone=row)
        store = _make_store(pool)
        with patch("aryx.store.oracle_workspace.load", side_effect=_mock_load):
            store.set_brief(1, None)  # type: ignore[arg-type]
        _, params = cur.execute.call_args[0]
        self.assertEqual(json.loads(params[0]), {})

    def test_empty_brief_stored_as_empty_json_object(self) -> None:
        row = (1, "WS", "", "", {}, "2024-01-01")
        pool, cur = _make_pool_cursor(fetchone=row)
        store = _make_store(pool)
        with patch("aryx.store.oracle_workspace.load", side_effect=_mock_load):
            store.set_brief(1, {})
        _, params = cur.execute.call_args[0]
        self.assertEqual(json.loads(params[0]), {})

    def test_full_five_field_brief_round_trips_through_json(self) -> None:
        """All 5 brief fields (including list-valued objectives/roles) survive json.dumps()."""
        row = (1, "WS", "", "", self._FULL_BRIEF, "2024-01-01")
        pool, cur = _make_pool_cursor(fetchone=row)
        store = _make_store(pool)
        with patch("aryx.store.oracle_workspace.load", side_effect=_mock_load):
            store.set_brief(1, self._FULL_BRIEF)
        _, params = cur.execute.call_args[0]
        self.assertEqual(json.loads(params[0]), self._FULL_BRIEF)

    # ── Oracle RETURNING path: brief arrives as a JSON string ─────────────────
    # oracledb thin allocates STRING vars for all RETURNING columns (_translate_sql
    # line 112). So row[4] from fetchone() is a JSON string, not a dict.
    # _parse_brief() must convert it back before the caller sees it.

    def test_returns_dict_when_oracle_returning_gives_json_string(self) -> None:
        """RETURNING brief as JSON text string → _parse_brief parses it to dict."""
        saved = {"domain": "HR", "aim": "test"}
        row = (1, "WS", "", "", json.dumps(saved), "2024-01-01")  # ← string, not dict
        pool, _ = _make_pool_cursor(fetchone=row)
        store = _make_store(pool)
        with patch("aryx.store.oracle_workspace.load", side_effect=_mock_load):
            result = store.set_brief(1, saved)
        self.assertEqual(result["brief"], saved)

    def test_returns_dict_when_oracle_returning_gives_dict(self) -> None:
        """RETURNING brief already a dict (OSON path) → returned as-is."""
        saved = {"domain": "HR", "aim": "test"}
        row = (1, "WS", "", "", saved, "2024-01-01")
        pool, _ = _make_pool_cursor(fetchone=row)
        store = _make_store(pool)
        with patch("aryx.store.oracle_workspace.load", side_effect=_mock_load):
            result = store.set_brief(1, saved)
        self.assertEqual(result["brief"], saved)

    def test_returns_empty_dict_when_oracle_returning_gives_null(self) -> None:
        """RETURNING brief as NULL → _parse_brief returns {}."""
        row = (1, "WS", "", "", None, "2024-01-01")
        pool, _ = _make_pool_cursor(fetchone=row)
        store = _make_store(pool)
        with patch("aryx.store.oracle_workspace.load", side_effect=_mock_load):
            result = store.set_brief(1, {})
        self.assertEqual(result["brief"], {})

    def test_full_brief_returned_correctly_from_json_string(self) -> None:
        """Full 5-field brief round-trips through the RETURNING JSON string path."""
        row = (1, "WS", "", "", json.dumps(self._FULL_BRIEF), "2024-01-01")
        pool, _ = _make_pool_cursor(fetchone=row)
        store = _make_store(pool)
        with patch("aryx.store.oracle_workspace.load", side_effect=_mock_load):
            result = store.set_brief(1, self._FULL_BRIEF)
        self.assertEqual(result["brief"]["objectives"], self._FULL_BRIEF["objectives"])
        self.assertEqual(result["brief"]["roles"], self._FULL_BRIEF["roles"])

    def test_returns_all_workspace_fields(self) -> None:
        """Result dict must contain id, name, description, context, brief, created_at."""
        brief = {"domain": "IT"}
        row = (42, "Main", "desc", "ctx", json.dumps(brief), "2025-01-01")
        pool, _ = _make_pool_cursor(fetchone=row)
        store = _make_store(pool)
        with patch("aryx.store.oracle_workspace.load", side_effect=_mock_load):
            result = store.set_brief(42, brief)
        self.assertEqual(result["id"], 42)
        self.assertEqual(result["name"], "Main")
        self.assertEqual(result["description"], "desc")
        self.assertEqual(result["context"], "ctx")
        self.assertIsNotNone(result.get("created_at"))


# ── _parse_brief unit tests ───────────────────────────────────────────────────

class TestParseBrief(unittest.TestCase):
    """_parse_brief() normalises the Oracle JSON column return value.

    oracledb thin returns Oracle 23ai JSON columns as either a Python str
    (JSON text — what we store via json.dumps()) or a Python dict (OSON binary).
    _parse_brief must handle all cases so callers always receive a dict.
    """

    def test_dict_returned_unchanged(self) -> None:
        d = {"domain": "Sales"}
        self.assertIs(_parse_brief(d), d)

    def test_none_returns_empty_dict(self) -> None:
        self.assertEqual(_parse_brief(None), {})

    def test_empty_dict_returned_unchanged(self) -> None:
        self.assertEqual(_parse_brief({}), {})

    def test_json_string_parsed_to_dict(self) -> None:
        s = '{"domain": "CRM", "aim": "Route tickets"}'
        self.assertEqual(_parse_brief(s), {"domain": "CRM", "aim": "Route tickets"})

    def test_full_brief_json_string_parsed(self) -> None:
        brief = {
            "domain": "CRM", "aim": "Match",
            "objectives": ["a", "b"], "scope": "Tickets", "roles": ["agent"],
        }
        self.assertEqual(_parse_brief(json.dumps(brief)), brief)

    def test_empty_json_object_string_returns_empty_dict(self) -> None:
        self.assertEqual(_parse_brief("{}"), {})

    def test_invalid_json_string_returns_empty_dict(self) -> None:
        self.assertEqual(_parse_brief("{not valid json}"), {})

    def test_json_array_string_returns_empty_dict(self) -> None:
        """Top-level array is not a valid brief dict — must return {}."""
        self.assertEqual(_parse_brief("[1, 2, 3]"), {})

    def test_json_scalar_string_returns_empty_dict(self) -> None:
        self.assertEqual(_parse_brief('"just a string"'), {})

    def test_nested_dict_preserved(self) -> None:
        d = {"meta": {"version": 1}, "domain": "HR"}
        self.assertEqual(_parse_brief(json.dumps(d)), d)


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
