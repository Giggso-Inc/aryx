"""Unit tests for oracle_pool.py — no live Oracle DB required.

All oracledb calls are stubbed so these tests run in CI without an ADB wallet.
"""
from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import MagicMock, patch


# ── Stub oracledb before importing oracle_pool ────────────────────────────────

def _stub_oracledb() -> None:
    """Install a minimal oracledb stub into sys.modules."""
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

    def _var(typ: str) -> MagicMock:
        v = MagicMock()
        v.getvalue.return_value = [None]
        return v

    # Fake cursor
    class _Cursor:
        def __init__(self) -> None:
            self.arraysize = 100
            self.rowcount = 0
            self._rows: list = []

        def var(self, typ: str) -> MagicMock:
            return _var(typ)

        def execute(self, sql: str, params: object = None) -> None:
            pass

        def executemany(self, sql: str, seq: object) -> None:
            pass

        def fetchone(self) -> tuple | None:
            return self._rows[0] if self._rows else None

        def fetchall(self) -> list:
            return list(self._rows)

        def fetchmany(self, size: int | None = None) -> list:
            return list(self._rows)

        def close(self) -> None:
            pass

        def __iter__(self):
            return iter(self._rows)

    mod._Cursor = _Cursor

    # Fake connection
    class _Conn:
        def cursor(self) -> _Cursor:
            return _Cursor()

        def commit(self) -> None:
            pass

        def rollback(self) -> None:
            pass

    mod._Conn = _Conn

    # Fake pool
    class _Pool:
        def acquire(self) -> _Conn:
            return _Conn()

        def release(self, conn: object) -> None:
            pass

    def create_pool(**kwargs: object) -> _Pool:
        return _Pool()

    mod.create_pool = create_pool
    sys.modules["oracledb"] = mod


def _stub_psycopg() -> None:
    """Stub psycopg so store/__init__.py import chain doesn't fail without it installed."""
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

from aryx.store.oracle_pool import (  # noqa: E402
    OracleCursorWrapper,
    _read_lob,
    _translate_sql,
    _unwrap_params,
)
from aryx.store.oracle_migrate import _split_blocks  # noqa: E402


# ── _split_blocks tests ───────────────────────────────────────────────────────

class TestSplitBlocks(unittest.TestCase):
    """Tests for the PL/SQL block splitter used by oracle_migrate."""

    def test_single_plsql_block(self) -> None:
        sql = "BEGIN\n  EXECUTE IMMEDIATE 'CREATE TABLE t (id NUMBER)';\nEXCEPTION WHEN OTHERS THEN NULL;\nEND;\n/"
        blocks = _split_blocks(sql)
        self.assertEqual(len(blocks), 1)
        self.assertIn("BEGIN", blocks[0])
        self.assertIn("END", blocks[0])

    def test_multiple_plsql_blocks(self) -> None:
        sql = "BEGIN\n  NULL;\nEND;\n/\nBEGIN\n  NULL;\nEND;\n/"
        blocks = _split_blocks(sql)
        self.assertEqual(len(blocks), 2)

    def test_trailing_plain_sql_after_slash(self) -> None:
        """Plain ALTER TABLE after the last '/' is split on ';'."""
        sql = "BEGIN\n  NULL;\nEND;\n/\nALTER TABLE t ADD (col VARCHAR2(100));"
        blocks = _split_blocks(sql)
        self.assertEqual(len(blocks), 2)
        self.assertIn("ALTER TABLE", blocks[1])

    def test_empty_sql(self) -> None:
        self.assertEqual(_split_blocks(""), [])

    def test_comment_only_lines_stripped_from_trailing(self) -> None:
        sql = "BEGIN\n  NULL;\nEND;\n/\n-- just a comment\n"
        blocks = _split_blocks(sql)
        self.assertEqual(len(blocks), 1)

    def test_noop_migration(self) -> None:
        """Migrations like 0010 contain only a comment and SELECT 1 FROM dual."""
        sql = "-- no-op\nSELECT 1 FROM dual"
        blocks = _split_blocks(sql)
        self.assertEqual(len(blocks), 1)
        self.assertIn("SELECT 1", blocks[0])


# ── _translate_sql tests ──────────────────────────────────────────────────────

def _make_cursor() -> OracleCursorWrapper:
    """Return a cursor wrapper backed by the stubbed oracledb cursor."""
    import oracledb
    raw = oracledb._Cursor()
    return OracleCursorWrapper(raw)


class TestTranslateSql(unittest.TestCase):
    """Tests for psycopg3 → oracledb SQL translation."""

    def test_named_params(self) -> None:
        cur = _make_cursor()
        result = _translate_sql("SELECT * FROM t WHERE id = %(wid)s", cur)
        self.assertEqual(result, "SELECT * FROM t WHERE id = :wid")

    def test_positional_params(self) -> None:
        cur = _make_cursor()
        result = _translate_sql("INSERT INTO t VALUES (%s, %s, %s)", cur)
        self.assertEqual(result, "INSERT INTO t VALUES (:1, :2, :3)")

    def test_type_cast_stripped(self) -> None:
        cur = _make_cursor()
        result = _translate_sql("SELECT data::jsonb FROM t", cur)
        self.assertNotIn("::", result)
        self.assertNotIn("jsonb", result)

    def test_multiple_cast_types(self) -> None:
        cur = _make_cursor()
        result = _translate_sql("SELECT a::text, b::int, c::bigint FROM t", cur)
        self.assertNotIn("::", result)

    def test_on_conflict_do_nothing_stripped(self) -> None:
        cur = _make_cursor()
        sql = "INSERT INTO t (id, v) VALUES (%s, %s) ON CONFLICT DO NOTHING"
        result = _translate_sql(sql, cur)
        self.assertNotIn("ON CONFLICT", result)
        self.assertTrue(cur._conflict_ignore)

    def test_on_conflict_do_update_stripped(self) -> None:
        # ON CONFLICT DO UPDATE SET … spans multiple lines; the full clause
        # including the SET body must be removed so Oracle gets a plain INSERT.
        cur = _make_cursor()
        sql = (
            "INSERT INTO aryx_ontology_type (workspace_id, name, attributes, status, source) "
            "VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (workspace_id, name) DO UPDATE "
            "SET attributes = EXCLUDED.attributes, "
            "    status = EXCLUDED.status, "
            "    source = EXCLUDED.source"
        )
        result = _translate_sql(sql, cur)
        self.assertNotIn("ON CONFLICT", result)
        self.assertNotIn("DO UPDATE", result)
        self.assertNotIn("EXCLUDED", result)
        self.assertTrue(cur._conflict_ignore)
        self.assertIn("VALUES (:1, :2, :3, :4, :5)", result)

    def test_no_conflict_flag_when_no_conflict_clause(self) -> None:
        cur = _make_cursor()
        _translate_sql("SELECT 1 FROM dual", cur)
        self.assertFalse(cur._conflict_ignore)

    def test_returning_rewritten_with_into(self) -> None:
        # 1 positional param (%s → :1); RETURNING INTO continues at :2
        cur = _make_cursor()
        result = _translate_sql("INSERT INTO t (name) VALUES (%s) RETURNING id", cur)
        self.assertIn("RETURNING id INTO :2", result)
        self.assertEqual(len(cur._out_vars), 1)

    def test_returning_multi_column(self) -> None:
        # 2 positional params (%s, %s → :1, :2); RETURNING INTO continues at :3, :4
        cur = _make_cursor()
        result = _translate_sql(
            "INSERT INTO t (a, b) VALUES (%s, %s) RETURNING id, name", cur
        )
        self.assertIn("RETURNING id, name INTO :3, :4", result)
        self.assertEqual(len(cur._out_vars), 2)

    def test_returning_named_params_use_r_prefix(self) -> None:
        # Named params (%(x)s) have _pos_counter=0 → fallback to :r0, :r1, ...
        cur = _make_cursor()
        result = _translate_sql(
            "INSERT INTO t (ws, name) VALUES (%(ws)s, %(n)s) RETURNING id", cur
        )
        self.assertIn("RETURNING id INTO :r0", result)
        self.assertEqual(len(cur._out_vars), 1)

    def test_returning_positional_4_params(self) -> None:
        # insert_entity pattern: 4 %s params → RETURNING id INTO :5
        cur = _make_cursor()
        result = _translate_sql(
            "INSERT INTO t (a, b, c, d) VALUES (%s, %s, %s, %s) RETURNING id", cur
        )
        self.assertIn("RETURNING id INTO :5", result)
        self.assertEqual(len(cur._out_vars), 1)

    def test_returning_not_doubled_when_into_present(self) -> None:
        """SQL already containing RETURNING...INTO must not get a second INTO appended."""
        cur = _make_cursor()
        sql = "INSERT INTO t VALUES (:1) RETURNING id INTO :r0"
        result = _translate_sql(sql, cur)
        # "INSERT INTO" + "RETURNING id INTO" = exactly 2 occurrences; no third added.
        self.assertEqual(result.count("INTO"), 2)
        # RETURNING clause must appear exactly once (not doubled).
        self.assertEqual(result.count("RETURNING"), 1)
        self.assertEqual(len(cur._out_vars), 0)  # no new out_vars allocated


# ── _unwrap_params tests ──────────────────────────────────────────────────────

class TestUnwrapParams(unittest.TestCase):
    """Tests for psycopg Json() duck-type unwrapping and Oracle coercions."""

    def test_none_passthrough(self) -> None:
        self.assertIsNone(_unwrap_params(None))

    def test_plain_string_passthrough(self) -> None:
        self.assertEqual(_unwrap_params("hello"), "hello")

    def test_list_serialized_to_json_string(self) -> None:
        # Bare lists (e.g. integer arrays for ANY/IN) → JSON string for Oracle CLOB.
        result = _unwrap_params([1, 2, 3])
        self.assertEqual(result, "[1, 2, 3]")

    def test_tuple_recursed_not_serialized(self) -> None:
        # Outer positional-params container stays as tuple, elements processed.
        result = _unwrap_params((1, "two", True))
        self.assertEqual(result, (1, "two", "Y"))

    def test_dict_recursed(self) -> None:
        result = _unwrap_params({"a": 1, "b": 2})
        self.assertEqual(result, {"a": 1, "b": 2})

    def test_bool_true_to_y(self) -> None:
        self.assertEqual(_unwrap_params(True), "Y")

    def test_bool_false_to_n(self) -> None:
        self.assertEqual(_unwrap_params(False), "N")

    def test_bool_in_tuple_converted(self) -> None:
        result = _unwrap_params((1, True, False))
        self.assertEqual(result, (1, "Y", "N"))

    def test_psycopg_json_serialized_to_string(self) -> None:
        fake_json = MagicMock()
        fake_json.obj = {"key": "value"}
        fake_json.dumps = lambda o: '{"key": "value"}'
        result = _unwrap_params(fake_json)
        self.assertEqual(result, '{"key": "value"}')

    def test_psycopg_json_dumps_none_falls_back_to_stdlib(self) -> None:
        # psycopg Json(obj) without a custom serializer stores dumps=None in
        # __slots__. hasattr() returns True but calling None() throws TypeError.
        # The fix checks callable(dumps_fn) and falls back to json.dumps.
        import json
        fake_json = MagicMock()
        fake_json.obj = ["_text"]
        fake_json.dumps = None  # simulates psycopg Json(["_text"]) — no custom dumps
        result = _unwrap_params(fake_json)
        self.assertEqual(result, json.dumps(["_text"]))

    def test_nested_json_in_list_serialized(self) -> None:
        # Json wrapper inside a list: the list becomes a JSON string,
        # and the wrapper inside is unwrapped before serialisation.
        import json
        fake_json = MagicMock()
        fake_json.obj = 42
        fake_json.dumps = lambda o: str(o)
        result = _unwrap_params([fake_json, "plain"])
        # list → JSON string; fake_json.obj=42 unwrapped to "42" (via dumps), then in list
        parsed = json.loads(result)
        self.assertEqual(parsed[1], "plain")


# ── ORA-00001 conflict-ignore tests ──────────────────────────────────────────

class TestConflictIgnore(unittest.TestCase):
    """ORA-00001 is swallowed when ON CONFLICT DO NOTHING was stripped."""

    def test_integrity_error_swallowed_when_conflict_ignore(self) -> None:
        import oracledb
        raw = oracledb._Cursor()
        cur = OracleCursorWrapper(raw)

        err = oracledb.IntegrityError("ORA-00001: unique constraint violated")
        err.args = ("ORA-00001: unique constraint violated",)

        with patch.object(raw, "execute", side_effect=err):
            # ON CONFLICT DO NOTHING triggers _conflict_ignore via _translate_sql.
            try:
                cur.execute(
                    "INSERT INTO t (id) VALUES (%s) ON CONFLICT DO NOTHING", (1,)
                )
            except oracledb.IntegrityError:
                self.fail("IntegrityError should have been swallowed")

    def test_integrity_error_raised_when_no_conflict_ignore(self) -> None:
        import oracledb
        raw = oracledb._Cursor()
        cur = OracleCursorWrapper(raw)

        err = oracledb.IntegrityError("ORA-00001: unique constraint violated")
        err.args = ("ORA-00001: unique constraint violated",)

        with patch.object(raw, "execute", side_effect=err):
            with self.assertRaises(oracledb.IntegrityError):
                cur.execute("INSERT INTO t VALUES (:1)", (1,))

    def test_other_integrity_error_always_raised(self) -> None:
        import oracledb
        raw = oracledb._Cursor()
        cur = OracleCursorWrapper(raw)
        cur._conflict_ignore = True

        err = oracledb.IntegrityError("ORA-02292: integrity constraint violated")
        err.args = ("ORA-02292: integrity constraint violated",)

        with patch.object(raw, "execute", side_effect=err):
            with self.assertRaises(oracledb.IntegrityError):
                cur.execute("DELETE FROM t WHERE id = :1", (1,))

    def test_executemany_integrity_error_swallowed_when_conflict_ignore(self) -> None:
        import oracledb
        raw = oracledb._Cursor()
        cur = OracleCursorWrapper(raw)

        err = oracledb.IntegrityError("ORA-00001: unique constraint violated")
        err.args = ("ORA-00001: unique constraint violated",)

        with patch.object(raw, "executemany", side_effect=err):
            try:
                cur.executemany(
                    "INSERT INTO t (id) VALUES (%s) ON CONFLICT DO NOTHING",
                    [(1,), (2,)],
                )
            except oracledb.IntegrityError:
                self.fail("IntegrityError should have been swallowed by executemany")

    def test_executemany_integrity_error_raised_when_no_conflict_ignore(self) -> None:
        import oracledb
        raw = oracledb._Cursor()
        cur = OracleCursorWrapper(raw)

        err = oracledb.IntegrityError("ORA-00001: unique constraint violated")
        err.args = ("ORA-00001: unique constraint violated",)

        with patch.object(raw, "executemany", side_effect=err):
            with self.assertRaises(oracledb.IntegrityError):
                cur.executemany("INSERT INTO t VALUES (:1)", [(1,), (2,)])


# ── _read_lob tests ───────────────────────────────────────────────────────────

class TestReadLob(unittest.TestCase):
    """_read_lob() calls .read() on LOB objects; passes everything else through."""

    def test_none_returns_none(self) -> None:
        self.assertIsNone(_read_lob(None))

    def test_plain_string_passthrough(self) -> None:
        self.assertEqual(_read_lob("hello"), "hello")

    def test_int_passthrough(self) -> None:
        self.assertEqual(_read_lob(42), 42)

    def test_dict_passthrough(self) -> None:
        d = {"a": 1}
        self.assertIs(_read_lob(d), d)

    def test_lob_read_called_and_result_returned(self) -> None:
        lob = MagicMock()
        lob.read.return_value = "clob content"
        self.assertEqual(_read_lob(lob), "clob content")
        lob.read.assert_called_once_with()

    def test_non_callable_read_attribute_not_invoked(self) -> None:
        class _FakeHasRead:
            read = "not callable"
        obj = _FakeHasRead()
        self.assertIs(_read_lob(obj), obj)


# ── Additional _translate_sql tests ──────────────────────────────────────────

class TestTranslateSqlExtensions(unittest.TestCase):
    """NOW(), LIMIT, LIMIT+OFFSET, and ORACLE:RETURNING hint translations."""

    def test_now_replaced_with_current_timestamp(self) -> None:
        cur = _make_cursor()
        result = _translate_sql("SELECT NOW()", cur)
        self.assertIn("CURRENT_TIMESTAMP", result)
        self.assertNotIn("NOW()", result)

    def test_now_case_insensitive(self) -> None:
        cur = _make_cursor()
        result = _translate_sql("SELECT now() FROM dual", cur)
        self.assertIn("CURRENT_TIMESTAMP", result)

    def test_limit_n_becomes_fetch_first(self) -> None:
        cur = _make_cursor()
        result = _translate_sql("SELECT * FROM t LIMIT 10", cur)
        self.assertIn("FETCH FIRST 10 ROWS ONLY", result)
        self.assertNotIn("LIMIT", result)

    def test_limit_n_offset_m_becomes_offset_fetch(self) -> None:
        cur = _make_cursor()
        result = _translate_sql("SELECT * FROM t LIMIT 10 OFFSET 5", cur)
        self.assertIn("OFFSET 5 ROWS FETCH NEXT 10 ROWS ONLY", result)
        self.assertNotIn("LIMIT", result)

    def test_oracle_returning_hint_sets_out_vars(self) -> None:
        cur = _make_cursor()
        sql = "-- ORACLE:RETURNING id\nINSERT INTO t (v) VALUES (:1) RETURNING id INTO :r0"
        _translate_sql(sql, cur)
        self.assertEqual(len(cur._out_vars), 1)

    def test_oracle_returning_hint_removed_from_sql(self) -> None:
        cur = _make_cursor()
        sql = "-- ORACLE:RETURNING id\nINSERT INTO t (v) VALUES (:1) RETURNING id INTO :r0"
        result = _translate_sql(sql, cur)
        self.assertNotIn("ORACLE:RETURNING", result)

    def test_oracle_returning_hint_multi_column(self) -> None:
        cur = _make_cursor()
        sql = "-- ORACLE:RETURNING id, name, ts\nINSERT INTO t (v) VALUES (:1) RETURNING id, name, ts INTO :r0, :r1, :r2"
        _translate_sql(sql, cur)
        self.assertEqual(len(cur._out_vars), 3)

    def test_vector_cast_preserved(self) -> None:
        """TO_VECTOR() in oracle override SQL must pass through unchanged."""
        cur = _make_cursor()
        sql = "INSERT INTO t (embedding) VALUES (TO_VECTOR(:1))"
        result = _translate_sql(sql, cur)
        self.assertIn("TO_VECTOR(:1)", result)

    def test_json_mergepatch_preserved(self) -> None:
        """JSON_MERGEPATCH() in oracle override SQL must pass through unchanged."""
        cur = _make_cursor()
        sql = "UPDATE t SET attrs = JSON_MERGEPATCH(attrs, :1) WHERE id = :2"
        result = _translate_sql(sql, cur)
        self.assertIn("JSON_MERGEPATCH", result)

    def test_sysdate_arithmetic_preserved(self) -> None:
        """SYSDATE - :1 date arithmetic must not be rewritten."""
        cur = _make_cursor()
        sql = "DELETE FROM aryx_job WHERE finished_at < SYSDATE - :1"
        result = _translate_sql(sql, cur)
        self.assertIn("SYSDATE - :1", result)


# ── Additional _unwrap_params tests ──────────────────────────────────────────

class TestUnwrapParamsExtensions(unittest.TestCase):
    """Empty strings are replaced with a single space (Oracle VARCHAR2 semantics)."""

    def test_empty_string_becomes_single_space(self) -> None:
        self.assertEqual(_unwrap_params(""), " ")

    def test_empty_string_in_tuple_replaced(self) -> None:
        result = _unwrap_params(("name", ""))
        self.assertEqual(result, ("name", " "))

    def test_empty_string_in_list_replaced(self) -> None:
        # Lists are serialized to JSON strings for Oracle CLOB; empty strings
        # inside are coerced to " " before serialisation.
        import json
        result = _unwrap_params(["a", "", "b"])
        self.assertEqual(json.loads(result), ["a", " ", "b"])

    def test_non_empty_string_unchanged(self) -> None:
        self.assertEqual(_unwrap_params("hello"), "hello")


# ── fetchone / fetchall LOB-read integration ──────────────────────────────────

class TestFetchWithLob(unittest.TestCase):
    """OracleCursorWrapper.fetchone/fetchall call _read_lob on every column."""

    def _lob(self, value: str) -> MagicMock:
        lob = MagicMock()
        lob.read.return_value = value
        return lob

    def test_fetchone_reads_lob_value(self) -> None:
        import oracledb
        raw = oracledb._Cursor()
        raw._rows = [(1, self._lob("some clob text"), "other")]
        cur = OracleCursorWrapper(raw)
        row = cur.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[1], "some clob text")
        self.assertEqual(row[2], "other")

    def test_fetchall_reads_lob_in_all_rows(self) -> None:
        import oracledb
        raw = oracledb._Cursor()
        raw._rows = [
            (1, self._lob("text1")),
            (2, self._lob("text2")),
        ]
        cur = OracleCursorWrapper(raw)
        rows = cur.fetchall()
        self.assertEqual(rows[0][1], "text1")
        self.assertEqual(rows[1][1], "text2")

    def test_fetchone_non_lob_values_passthrough(self) -> None:
        import oracledb
        raw = oracledb._Cursor()
        raw._rows = [(1, "plain string", 42, None)]
        cur = OracleCursorWrapper(raw)
        row = cur.fetchone()
        self.assertEqual(row, (1, "plain string", 42, None))

    def test_fetchone_returns_none_when_no_rows(self) -> None:
        import oracledb
        raw = oracledb._Cursor()
        raw._rows = []
        cur = OracleCursorWrapper(raw)
        self.assertIsNone(cur.fetchone())

    def test_fetchall_returns_empty_list_when_no_rows(self) -> None:
        import oracledb
        raw = oracledb._Cursor()
        raw._rows = []
        cur = OracleCursorWrapper(raw)
        self.assertEqual(cur.fetchall(), [])


# ── LIMIT / OFFSET translation tests ─────────────────────────────────────────

class TestLimitTranslation(unittest.TestCase):
    """LIMIT / OFFSET → Oracle FETCH FIRST / OFFSET ROWS FETCH NEXT."""

    def test_limit_literal_translated(self) -> None:
        cur = _make_cursor()
        result = _translate_sql("SELECT * FROM t ORDER BY id LIMIT 50", cur)
        self.assertNotIn("LIMIT", result)
        self.assertIn("FETCH FIRST 50 ROWS ONLY", result)

    def test_limit_positional_param_translated(self) -> None:
        # After %s → :N substitution, LIMIT %s becomes LIMIT :1
        cur = _make_cursor()
        sql = "SELECT * FROM t WHERE workspace_id = :1 ORDER BY id LIMIT :2"
        result = _translate_sql(sql, cur)
        self.assertNotIn("LIMIT", result)
        self.assertIn("FETCH FIRST :2 ROWS ONLY", result)

    def test_limit_named_param_translated(self) -> None:
        # After %(limit)s → :limit substitution
        cur = _make_cursor()
        sql = "SELECT * FROM t ORDER BY created_at DESC LIMIT :limit"
        result = _translate_sql(sql, cur)
        self.assertNotIn("LIMIT", result)
        self.assertIn("FETCH FIRST :limit ROWS ONLY", result)

    def test_limit_offset_literal_translated(self) -> None:
        cur = _make_cursor()
        sql = "SELECT * FROM t ORDER BY id LIMIT 20 OFFSET 40"
        result = _translate_sql(sql, cur)
        self.assertNotIn("LIMIT", result)
        self.assertIn("OFFSET 40 ROWS FETCH NEXT 20 ROWS ONLY", result)

    def test_limit_offset_positional_params_translated(self) -> None:
        cur = _make_cursor()
        sql = "SELECT * FROM t WHERE ws = :1 ORDER BY id LIMIT :2 OFFSET :3"
        result = _translate_sql(sql, cur)
        self.assertNotIn("LIMIT", result)
        self.assertIn("OFFSET :3 ROWS FETCH NEXT :2 ROWS ONLY", result)


# ── _save_batch per-row entity insert tests ───────────────────────────────────

def _stub_falkordb() -> None:
    """Stub falkordb so oracle_graph_store can be imported without the library."""
    import sys
    import types
    if "falkordb" in sys.modules:
        return
    mod = types.ModuleType("falkordb")
    mod.FalkorDB = MagicMock
    sys.modules["falkordb"] = mod


_DUMMY_SQL = "INSERT INTO t (a) VALUES (:1) RETURNING id INTO :2"
# entity_store does `from aryx.queries import load` — patch the name in that module
_load_patcher = patch("aryx.store.entity_store.load", return_value=_DUMMY_SQL)


class TestSaveBatch(unittest.TestCase):
    """entity_store._save_batch: bulk insert via identity sequence pre-fetch, no per-row loop."""

    @classmethod
    def setUpClass(cls) -> None:
        _stub_psycopg()
        _stub_oracledb()
        _load_patcher.start()

    @classmethod
    def tearDownClass(cls) -> None:
        _load_patcher.stop()

    def _make_cursor(self) -> tuple:
        """Return (OracleCursorWrapper, many_calls) — execute is a no-op."""
        import oracledb
        from aryx.store.oracle_pool import OracleCursorWrapper
        raw_cur = oracledb._Cursor()
        wrapped = OracleCursorWrapper(raw_cur)
        wrapped.execute = lambda sql, params=None: None

        many_calls: list = []
        wrapped.executemany = lambda sql, seq: many_calls.append(list(seq))

        return wrapped, many_calls

    def _make_results(self, n: int):
        from aryx.models import ResolvedEntity, EntityMember
        return [
            (ResolvedEntity(ontology_type="T", attributes={"name": str(i)},
                            confidence=1.0, provenance=None, conflicts=None),
             [EntityMember(landed_record_id=i * 10)])
            for i in range(n)
        ]

    def _store(self):
        from aryx.store.entity_store import EntityStore
        store = EntityStore.__new__(EntityStore)
        store._ws = 1
        store._pool = None
        return store

    def test_save_batch_uses_executemany_not_loop(self) -> None:
        """_save_batch must call executemany for entities (no per-row execute loop)."""
        import aryx.store.entity_store as es
        wrapped, many_calls = self._make_cursor()
        results = self._make_results(3)

        with patch.object(es, "_fetch_entity_ids", return_value=[101, 102, 103]):
            self._store()._save_batch(wrapped, results)

        # 1st executemany = entity insert, 2nd = member insert
        self.assertEqual(len(many_calls), 2)
        # Entity rows have id as first element: 101, 102, 103
        self.assertEqual([r[0] for r in many_calls[0]], [101, 102, 103])

    def test_save_batch_member_rows_use_fetched_ids(self) -> None:
        """Member rows must reference the IDs returned by _fetch_entity_ids."""
        import aryx.store.entity_store as es
        wrapped, many_calls = self._make_cursor()
        results = self._make_results(3)

        with patch.object(es, "_fetch_entity_ids", return_value=[201, 202, 203]):
            self._store()._save_batch(wrapped, results)

        member_rows = many_calls[1]
        self.assertEqual([r[1] for r in member_rows], [201, 202, 203])

    def test_save_batch_no_executemany_when_empty(self) -> None:
        """No executemany calls when results list is empty."""
        import aryx.store.entity_store as es
        wrapped, many_calls = self._make_cursor()

        with patch.object(es, "_fetch_entity_ids", return_value=[]):
            self._store()._save_batch(wrapped, [])

        self.assertEqual(many_calls, [])


# ── oracle_graph_store chunking tests ─────────────────────────────────────────

_stub_falkordb()

# Import directly to bypass aryx.graph.__init__ → falkordb chain
import importlib.util as _ilu
import sys as _sys
_spec = _ilu.spec_from_file_location(
    "aryx.graph.oracle_graph_store",
    "/home/halcyoona/giggso/github_repo/aryx/aryx/src/aryx/graph/oracle_graph_store.py",
)
_mod = _ilu.module_from_spec(_spec)
_sys.modules["aryx.graph.oracle_graph_store"] = _mod
_spec.loader.exec_module(_mod)
_OracleGraphStore = _mod.OracleGraphStore


_GRAPH_DUMMY_SQL = "MERGE INTO t USING dual ON (1=1) WHEN MATCHED THEN UPDATE SET a=:1 WHEN NOT MATCHED THEN INSERT (a) VALUES (:1)"
# _mod.load is the `load` name bound inside the oracle_graph_store module — swap directly.
_graph_load_real = _mod.load
_mod.load = lambda *_: _GRAPH_DUMMY_SQL


class TestGraphStoreBatchChunking(unittest.TestCase):
    """add_entities_batch must split executemany into ≤100-row chunks."""

    def _make_store(self) -> tuple:
        """Return (OracleGraphStore, executemany_chunk_sizes)."""
        from contextlib import contextmanager
        executemany_calls: list[int] = []

        class _FakeCur:
            def executemany(self, sql, rows):
                executemany_calls.append(len(rows))
            def execute(self, sql, params=None):
                pass
            def fetchall(self):
                return []
            def __enter__(self):
                return self
            def __exit__(self, *_):
                pass

        class _FakeConn:
            def cursor(self):
                return _FakeCur()
            def __enter__(self):
                return self
            def __exit__(self, *_):
                pass

        class _FakePool:
            @contextmanager
            def connection(self):
                yield _FakeConn()

        store = _OracleGraphStore.__new__(_OracleGraphStore)
        store._workspace_id = 1
        store._pool = _FakePool()
        return store, executemany_calls

    def test_add_entities_batch_chunks_at_100(self) -> None:
        store, calls = self._make_store()
        rows = [(i, "T", {"name": str(i)}, None, None) for i in range(250)]
        store.add_entities_batch(rows)
        self.assertEqual(calls, [100, 100, 50])

    def test_add_entities_batch_small_batch_single_chunk(self) -> None:
        store, calls = self._make_store()
        rows = [(i, "T", {"name": str(i)}, None, None) for i in range(30)]
        store.add_entities_batch(rows)
        self.assertEqual(calls, [30])

    def test_add_relationships_batch_chunks_at_100(self) -> None:
        store, calls = self._make_store()
        rows = [(i, i + 1, "rel") for i in range(210)]
        store.add_relationships_batch(rows)
        self.assertEqual(calls, [100, 100, 10])

    def test_add_entities_batch_empty_is_noop(self) -> None:
        store, calls = self._make_store()
        store.add_entities_batch([])
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
