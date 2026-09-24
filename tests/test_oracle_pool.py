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
    # Sentinel used in the JSON output type handler identity check (is DB_TYPE_JSON).
    # object() is stable for the lifetime of the stub (sys.modules caches it).
    mod.DB_TYPE_JSON = object()

    class _IntegrityError(Exception):
        pass

    class _Error(Exception):
        pass

    mod.IntegrityError = _IntegrityError
    mod.Error = _Error

    def _var(typ: object, arraysize: int | None = None,
             outconverter: object = None) -> MagicMock:
        v = MagicMock()
        v.getvalue.return_value = [None]
        v._outconverter = outconverter
        return v

    # Fake cursor
    class _Cursor:
        def __init__(self) -> None:
            self.arraysize = 100
            self.rowcount = 0
            self._rows: list = []
            self.outputtypehandler = None  # set by OracleCursorWrapper.__init__
            self._last_outconverter = None  # captured on var() — used by handler tests

        def var(self, typ: object, arraysize: int | None = None,
                outconverter: object = None) -> MagicMock:
            self._last_outconverter = outconverter
            return _var(typ, arraysize=arraysize, outconverter=outconverter)

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
    _coerce_clob,
    _hint_clob,
    _hint_clob_many,
    _read_lob,
    _restore_empty_string,
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

    def test_on_conflict_do_update_raises(self) -> None:
        # ON CONFLICT DO UPDATE has no safe generic Oracle translation --
        # stripping it identically to DO NOTHING would silently reduce a
        # real upsert to insert-or-ignore, discarding the intended update
        # on every conflict with no error (found by post-merge review: a
        # systemic trap for the next such query added without an explicit
        # Oracle MERGE override). Every real caller in this codebase either
        # has its own queries/oracle/<name>.sql MERGE override (so this
        # generic path never actually runs for them), or -- like
        # upsert_bml_tier2_cache.sql -- guarantees no conflict can occur
        # before calling, with a plain-INSERT override of its own.
        cur = _make_cursor()
        sql = (
            "INSERT INTO aryx_ontology_type (workspace_id, name, attributes, status, source) "
            "VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (workspace_id, name) DO UPDATE "
            "SET attributes = EXCLUDED.attributes, "
            "    status = EXCLUDED.status, "
            "    source = EXCLUDED.source"
        )
        with self.assertRaises(ValueError):
            _translate_sql(sql, cur)

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


# ── _restore_empty_string tests ───────────────────────────────────────────────

class TestRestoreEmptyString(unittest.TestCase):
    """Undoes the write-side '' -> ' ' NOT NULL workaround on fetch."""

    def test_single_space_becomes_empty_string(self) -> None:
        self.assertEqual(_restore_empty_string(" "), "")

    def test_two_spaces_passthrough(self) -> None:
        # Only the exact single-space marker is restored -- a real multi-char
        # whitespace value is left alone.
        self.assertEqual(_restore_empty_string("  "), "  ")

    def test_non_space_string_passthrough(self) -> None:
        self.assertEqual(_restore_empty_string("hello"), "hello")

    def test_none_passthrough(self) -> None:
        self.assertIsNone(_restore_empty_string(None))

    def test_int_passthrough(self) -> None:
        self.assertEqual(_restore_empty_string(42), 42)


class TestFetchRestoresEmptyStrings(unittest.TestCase):
    """fetchone/fetchall/fetchmany/__iter__ all restore '' from the ' ' marker."""

    def _cursor_with_rows(self, rows: list[tuple]) -> OracleCursorWrapper:
        import oracledb
        raw = oracledb._Cursor()
        raw._rows = rows
        return OracleCursorWrapper(raw)

    def test_fetchone_restores_empty_string(self) -> None:
        cur = self._cursor_with_rows([(1, " ", "real value")])
        row = cur.fetchone()
        self.assertEqual(row, (1, "", "real value"))

    def test_fetchall_restores_empty_string(self) -> None:
        cur = self._cursor_with_rows([(1, " "), (2, "kept")])
        rows = cur.fetchall()
        self.assertEqual(rows, [(1, ""), (2, "kept")])

    def test_fetchmany_restores_empty_string(self) -> None:
        cur = self._cursor_with_rows([(1, " ")])
        rows = cur.fetchmany(10)
        self.assertEqual(rows, [(1, "")])

    def test_iter_restores_empty_string(self) -> None:
        cur = self._cursor_with_rows([(1, " "), (2, "x")])
        self.assertEqual(list(cur), [(1, ""), (2, "x")])

    def test_fetchall_restores_after_lob_read(self) -> None:
        """A LOB whose .read() returns ' ' is also restored to ''."""
        lob = MagicMock()
        lob.read.return_value = " "
        cur = self._cursor_with_rows([(1, lob)])
        self.assertEqual(cur.fetchall(), [(1, "")])


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
import pathlib as _pathlib
import sys as _sys
_store_path = _pathlib.Path(__file__).parents[1] / "src/aryx/graph/oracle_graph_store.py"
_spec = _ilu.spec_from_file_location(
    "aryx.graph.oracle_graph_store",
    _store_path,
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

    def test_add_entities_batch_chunks_at_500(self) -> None:
        """_CHUNK_MAX_ROWS=500 (raised from 25 -- see P8/graph-projection fix
        in docs/SCALABILITY_BOTTLENECKS.md: the row cap, not the byte cap,
        was the binding constraint and caused far more round-trips to Oracle
        Cloud than the byte budget actually required).

        Chunks now run concurrently by default (Phase 4 Part B,
        oracle_graph_batch_workers) -- completion order isn't guaranteed by
        ThreadPoolExecutor/as_completed, so this asserts the set of chunk
        sizes, not submission order."""
        store, calls = self._make_store()
        rows = [(i, "T", {"name": str(i)}, None, None) for i in range(1250)]
        store.add_entities_batch(rows)
        self.assertEqual(sorted(calls), [250, 500, 500])

    def test_add_entities_batch_small_batch_single_chunk(self) -> None:
        store, calls = self._make_store()
        rows = [(i, "T", {"name": str(i)}, None, None) for i in range(30)]
        store.add_entities_batch(rows)
        self.assertEqual(calls, [30])

    def test_add_relationships_batch_chunks_at_500(self) -> None:
        """Order-independent for the same reason as the entities test above."""
        store, calls = self._make_store()
        rows = [(i, i + 1, "rel") for i in range(1050)]
        store.add_relationships_batch(rows)
        self.assertEqual(sorted(calls), [50, 500, 500])

    def test_add_entities_batch_empty_is_noop(self) -> None:
        store, calls = self._make_store()
        store.add_entities_batch([])
        self.assertEqual(calls, [])


class TestGraphStoreBatchConcurrency(unittest.TestCase):
    """Phase 4 Part B: add_entities_batch/add_relationships_batch run their
    independent chunks concurrently, each on its own pooled connection --
    never sharing one connection across threads (the pattern already
    proven safe for ProjectionStore/schema-FK batches/embedding prefetch
    in Phases 1-3)."""

    def _make_store(self, workers: int = 4) -> tuple:
        """Return (OracleGraphStore, chunk_sizes, connection_ids_used)."""
        from contextlib import contextmanager
        import threading

        chunk_sizes: list[int] = []
        conn_ids: list[int] = []
        lock = threading.Lock()

        class _FakeCur:
            def executemany(self, sql, rows):
                with lock:
                    chunk_sizes.append(len(rows))
            def execute(self, sql, params=None):
                pass
            def fetchall(self):
                return []
            def __enter__(self):
                return self
            def __exit__(self, *_):
                pass

        class _FakeConn:
            def __init__(self):
                with lock:
                    conn_ids.append(id(self))
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
        settings = MagicMock()
        settings.oracle_graph_batch_workers = workers
        patcher = patch("aryx.graph.oracle_graph_store_batch.get_settings", return_value=settings)
        patcher.start()
        self.addCleanup(patcher.stop)
        return store, chunk_sizes, conn_ids

    def test_multiple_chunks_use_separate_connections_when_concurrent(self) -> None:
        store, chunk_sizes, conn_ids = self._make_store(workers=4)
        rows = [(i, "T", {"name": str(i)}, None, None) for i in range(1250)]

        store.add_entities_batch(rows)

        self.assertEqual(sorted(chunk_sizes), [250, 500, 500])
        # 3 chunks -> 3 distinct connections, never one shared across chunks.
        self.assertEqual(len(conn_ids), 3)
        self.assertEqual(len(set(conn_ids)), 3)

    def test_workers_1_falls_back_to_one_connection_sequential(self) -> None:
        """Regression guard: oracle_graph_batch_workers=1 must reproduce the
        original pre-Phase-4-Part-B behavior exactly -- one connection for
        the whole batch, chunks in submission order."""
        store, chunk_sizes, conn_ids = self._make_store(workers=1)
        rows = [(i, "T", {"name": str(i)}, None, None) for i in range(1250)]

        store.add_entities_batch(rows)

        self.assertEqual(chunk_sizes, [500, 500, 250])
        self.assertEqual(len(set(conn_ids)), 1)

    def test_relationships_batch_also_uses_separate_connections(self) -> None:
        store, chunk_sizes, conn_ids = self._make_store(workers=4)
        rows = [(i, i + 1, "rel") for i in range(1050)]

        store.add_relationships_batch(rows)

        self.assertEqual(sorted(chunk_sizes), [50, 500, 500])
        self.assertEqual(len(set(conn_ids)), 3)

    def test_on_batch_final_total_is_correct_regardless_of_completion_order(self) -> None:
        store, _chunk_sizes, _conn_ids = self._make_store(workers=4)
        rows = [(i, "T", {"name": str(i)}, None, None) for i in range(1250)]
        totals: list[int] = []

        store.add_entities_batch(rows, on_batch=totals.append)

        self.assertEqual(len(totals), 3)
        # Running total must be monotonically increasing and end at the
        # full row count, regardless of which chunk completed first.
        self.assertEqual(totals[-1], 1250)
        self.assertTrue(all(a < b for a, b in zip(totals, totals[1:])))


class TestOracleGraphBatchWorkersDefault(unittest.TestCase):
    """Default stays 4 despite a mixed live measurement against a real
    Oracle ADB (docs/ingestion/SPARK_PARALLEL_MIGRATION_ANALYSIS_2026-09-
    23.md Phase 4 Part B): entities regressed (68.0s -> 74.7s at workers=4),
    relationships were roughly flat (25.7s -> 24.0s). One measurement on
    one ADB tier wasn't treated as reason enough to disable the mechanism
    by default -- ARYX_ORACLE_GRAPH_BATCH_WORKERS=1 opts out."""

    def test_default_is_four(self) -> None:
        from aryx.config import Settings
        self.assertEqual(Settings.model_fields["oracle_graph_batch_workers"].default, 4)

    def test_env_override(self) -> None:
        from aryx.config import Settings
        with patch.dict("os.environ", {"ARYX_ORACLE_GRAPH_BATCH_WORKERS": "1"}):
            s = Settings(_env_file=None)
            self.assertEqual(s.oracle_graph_batch_workers, 1)


class TestGraphStoreFullRebuildInsert(unittest.TestCase):
    """Phase 4 Part B follow-up: project_graph()'s full-rebuild path uses
    plain INSERT (insert_graph_vertex/insert_graph_edge), not MERGE --
    live-measured that a 500-row MERGE executemany() batch hung 180+
    seconds against a real Oracle ADB with zero conflicting rows and zero
    lock contention, while the equivalent INSERT batch completed in well
    under a second (docs/ingestion/SPARK_PARALLEL_MIGRATION_ANALYSIS_2026-
    09-23.md). project_incremental() must keep using MERGE -- it never
    calls clear(), so rows may legitimately already exist."""

    def _make_store(self):
        """Return (store, sql_seen, rows_seen) -- sql_seen/rows_seen are
        parallel lists, one entry per executemany() call."""
        from contextlib import contextmanager

        sql_seen: list[str] = []
        rows_seen: list[list] = []

        class _FakeCur:
            def executemany(self, sql, rows):
                sql_seen.append(sql)
                rows_seen.append(rows)
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
        settings = MagicMock()
        settings.oracle_graph_batch_workers = 1  # sequential -> deterministic sql_seen order
        patcher = patch("aryx.graph.oracle_graph_store_batch.get_settings", return_value=settings)
        patcher.start()
        self.addCleanup(patcher.stop)
        return store, sql_seen, rows_seen

    @staticmethod
    def _code_only(sql: str) -> str:
        return "\n".join(ln for ln in sql.splitlines() if not ln.strip().startswith("--"))

    def test_entities_full_rebuild_uses_plain_insert(self) -> None:
        store, sql_seen, _rows_seen = self._make_store()
        rows = [(1, "T", {"name": "a"}, None, None)]

        store.add_entities_batch(rows, full_rebuild=True)

        code = self._code_only(sql_seen[0])
        self.assertIn("INSERT INTO aryx_graph_vertex", code)
        self.assertNotIn("MERGE", code)

    def test_entities_default_still_uses_merge(self) -> None:
        """Regression guard: project_incremental() calls this with no
        full_rebuild kwarg, and must keep getting MERGE."""
        store, sql_seen, _rows_seen = self._make_store()
        rows = [(1, "T", {"name": "a"}, None, None)]

        store.add_entities_batch(rows)

        self.assertIn("MERGE INTO aryx_graph_vertex", sql_seen[0])

    def test_relationships_full_rebuild_uses_plain_insert(self) -> None:
        store, sql_seen, _rows_seen = self._make_store()

        store.add_relationships_batch([(1, 2, "REL")], full_rebuild=True)

        code = self._code_only(sql_seen[0])
        self.assertIn("INSERT INTO aryx_graph_edge", code)
        self.assertNotIn("MERGE", code)

    def test_relationships_default_still_uses_merge(self) -> None:
        store, sql_seen, _rows_seen = self._make_store()

        store.add_relationships_batch([(1, 2, "REL")])

        self.assertIn("MERGE INTO aryx_graph_edge", sql_seen[0])

    def test_relationships_full_rebuild_deduplicates_before_insert(self) -> None:
        """A plain INSERT has no upsert semantics -- an accidental
        duplicate (source, target, name) from the RDB (which has no
        uniqueness constraint on that triple) would raise ORA-00001
        without this dedup, where MERGE silently absorbed it before."""
        store, _sql_seen, rows_seen = self._make_store()

        store.add_relationships_batch(
            [(1, 2, "REL"), (1, 2, "REL"), (3, 4, "REL")], full_rebuild=True)

        self.assertEqual(len(rows_seen[0]), 2)  # deduped: (1,2,REL) once + (3,4,REL)

    def test_relationships_default_does_not_deduplicate(self) -> None:
        """Regression guard: MERGE already handles duplicates safely, so
        the incremental path's row count (and hence its on_batch totals)
        must stay unchanged -- dedup is full_rebuild-only."""
        store, _sql_seen, rows_seen = self._make_store()

        store.add_relationships_batch([(1, 2, "REL"), (1, 2, "REL"), (3, 4, "REL")])

        self.assertEqual(len(rows_seen[0]), 3)


# ── JSON output type handler tests ───────────────────────────────────────────

class TestJsonOutputTypeHandler(unittest.TestCase):
    """OracleCursorWrapper installs an outputtypehandler that normalises
    Oracle native JSON columns (DB_TYPE_JSON) to Python dicts/lists on
    every SELECT fetch — regardless of whether Oracle stored them as OSON
    binary or JSON text (the latter is what our json.dumps() binding produces).
    """

    def _raw(self):
        import oracledb
        return oracledb._Cursor()

    def _handler_and_raw(self):
        raw = self._raw()
        OracleCursorWrapper(raw)
        return raw.outputtypehandler, raw

    def _outconverter(self):
        import oracledb
        handler, raw = self._handler_and_raw()
        meta = MagicMock()
        meta.type_code = oracledb.DB_TYPE_JSON
        handler(raw, meta)
        return raw._last_outconverter

    # ── installation ──────────────────────────────────────────────────────────

    def test_handler_installed_on_raw_cursor(self) -> None:
        raw = self._raw()
        OracleCursorWrapper(raw)
        self.assertTrue(callable(raw.outputtypehandler))

    # ── non-JSON type → None (oracledb uses default behaviour) ───────────────

    def test_handler_returns_none_for_non_json_type(self) -> None:
        import oracledb
        handler, raw = self._handler_and_raw()
        meta = MagicMock()
        meta.type_code = oracledb.STRING
        self.assertIsNone(handler(raw, meta))

    def test_handler_returns_none_for_unknown_type(self) -> None:
        handler, raw = self._handler_and_raw()
        meta = MagicMock()
        meta.type_code = object()  # arbitrary unknown sentinel
        self.assertIsNone(handler(raw, meta))

    # ── DB_TYPE_JSON → returns a cursor.var() ─────────────────────────────────

    def test_handler_returns_var_for_json_type(self) -> None:
        import oracledb
        handler, raw = self._handler_and_raw()
        meta = MagicMock()
        meta.type_code = oracledb.DB_TYPE_JSON
        self.assertIsNotNone(handler(raw, meta))

    def test_handler_registers_outconverter(self) -> None:
        conv = self._outconverter()
        self.assertTrue(callable(conv))

    # ── outconverter: JSON text string → Python dict ──────────────────────────

    def test_outconverter_parses_json_object_string(self) -> None:
        conv = self._outconverter()
        result = conv('{"domain": "Sales", "aim": "Match experts"}')
        self.assertEqual(result, {"domain": "Sales", "aim": "Match experts"})

    def test_outconverter_parses_full_brief_json(self) -> None:
        import json
        conv = self._outconverter()
        brief = {
            "domain": "CRM", "aim": "Route tickets",
            "objectives": ["match", "score"],
            "scope": "Support tickets only",
            "roles": ["agent", "customer"],
        }
        self.assertEqual(conv(json.dumps(brief)), brief)

    def test_outconverter_parses_json_array_string(self) -> None:
        conv = self._outconverter()
        self.assertEqual(conv('[1, 2, 3]'), [1, 2, 3])

    def test_outconverter_parses_empty_object_string(self) -> None:
        conv = self._outconverter()
        self.assertEqual(conv('{}'), {})

    # ── outconverter: already-Python value → pass through (OSON path) ────────

    def test_outconverter_passes_through_dict(self) -> None:
        conv = self._outconverter()
        d = {"domain": "already parsed"}
        self.assertIs(conv(d), d)

    def test_outconverter_passes_through_list(self) -> None:
        conv = self._outconverter()
        lst = [1, 2, 3]
        self.assertIs(conv(lst), lst)

    def test_outconverter_passes_through_none(self) -> None:
        conv = self._outconverter()
        self.assertIsNone(conv(None))

    def test_outconverter_passes_through_integer(self) -> None:
        # JSON scalar values (rare for our columns, but handler must not crash)
        conv = self._outconverter()
        self.assertEqual(conv(42), 42)


# ── CLOB-handling golden-master tests (Raven Style Compliance Plan, Phase 2a,
# §6 item 1) -- added 2026-09-03, before extracting _hint_clob/_coerce_clob/
# _hint_clob_many into their own module. These 3 functions had zero prior
# test coverage despite being exactly where this project's ORA-03146/
# ORA-22848 production bugs (PRs #310-#311) lived -- a real gap, not a
# mechanical formality.

class _FakeOracledb:
    DB_TYPE_CLOB = "DB_TYPE_CLOB"


class TestHintClob(unittest.TestCase):
    def test_none_params_is_a_noop(self) -> None:
        cursor = MagicMock()
        _hint_clob(cursor, None, _FakeOracledb())
        cursor.setinputsizes.assert_not_called()

    def test_named_params_hints_only_oversized_strings(self) -> None:
        cursor = MagicMock()
        params = {"short": "a", "long": "x" * 32768}
        _hint_clob(cursor, params, _FakeOracledb())
        cursor.setinputsizes.assert_called_once_with(long="DB_TYPE_CLOB")

    def test_named_params_no_hint_when_all_short(self) -> None:
        cursor = MagicMock()
        params = {"a": "short", "b": "also short"}
        _hint_clob(cursor, params, _FakeOracledb())
        cursor.setinputsizes.assert_not_called()

    def test_positional_params_hints_by_index(self) -> None:
        cursor = MagicMock()
        params = ["short", "x" * 32768, 42]
        _hint_clob(cursor, params, _FakeOracledb())
        cursor.setinputsizes.assert_called_once_with(None, "DB_TYPE_CLOB", None)

    def test_positional_params_no_hint_when_none_oversized(self) -> None:
        cursor = MagicMock()
        params = ["short", "also short"]
        _hint_clob(cursor, params, _FakeOracledb())
        cursor.setinputsizes.assert_not_called()


class TestCoerceClob(unittest.TestCase):
    def _cursor_with_var(self) -> MagicMock:
        cursor = MagicMock()
        cvar = MagicMock()
        cursor.var.return_value = cvar
        return cursor, cvar

    def test_none_params_passthrough(self) -> None:
        cursor, _ = self._cursor_with_var()
        self.assertIsNone(_coerce_clob(None, cursor, _FakeOracledb()))

    def test_dict_default_only_coerces_oversized_strings(self) -> None:
        cursor, cvar = self._cursor_with_var()
        params = {"short": "a", "long": "x" * 32768}
        out = _coerce_clob(params, cursor, _FakeOracledb())
        self.assertEqual(out["short"], "a")
        self.assertIs(out["long"], cvar)
        cvar.setvalue.assert_called_once_with(0, "x" * 32768)

    def test_dict_force_coerces_all_strings_regardless_of_length(self) -> None:
        cursor, cvar = self._cursor_with_var()
        params = {"short": "a", "num": 5}
        out = _coerce_clob(params, cursor, _FakeOracledb(), force=True)
        self.assertIs(out["short"], cvar)
        self.assertEqual(out["num"], 5)

    def test_dict_exclude_keys_never_coerced_even_when_forced(self) -> None:
        cursor, _ = self._cursor_with_var()
        params = {"on_key": "short", "other": "short"}
        out = _coerce_clob(
            params, cursor, _FakeOracledb(), force=True, exclude=frozenset({"on_key"}),
        )
        self.assertEqual(out["on_key"], "short")
        self.assertNotEqual(out["other"], "short")  # coerced to the cvar mock

    def test_list_params_default_only_coerces_oversized(self) -> None:
        cursor, cvar = self._cursor_with_var()
        out = _coerce_clob(["short", "x" * 32768], cursor, _FakeOracledb())
        self.assertEqual(out[0], "short")
        self.assertIs(out[1], cvar)
        self.assertIsInstance(out, list)

    def test_tuple_params_returns_a_tuple(self) -> None:
        cursor, _ = self._cursor_with_var()
        out = _coerce_clob(("a", "b"), cursor, _FakeOracledb(), force=True)
        self.assertIsInstance(out, tuple)


class TestHintClobMany(unittest.TestCase):
    def test_empty_seq_is_a_noop(self) -> None:
        cursor = MagicMock()
        _hint_clob_many(cursor, [], _FakeOracledb())
        cursor.setinputsizes.assert_not_called()

    def test_dict_rows_default_hints_only_columns_with_an_oversized_value(self) -> None:
        cursor = MagicMock()
        seq = [{"a": "short", "b": "short"}, {"a": "x" * 32768, "b": "short"}]
        _hint_clob_many(cursor, seq, _FakeOracledb())
        cursor.setinputsizes.assert_called_once_with(a="DB_TYPE_CLOB")

    def test_dict_rows_force_merge_hints_every_string_column_except_excluded(self) -> None:
        cursor = MagicMock()
        seq = [{"a": "short", "b": "short", "on_key": "short"}]
        _hint_clob_many(cursor, seq, _FakeOracledb(), force_merge=True, on_excl=frozenset({"on_key"}))
        called_kwargs = cursor.setinputsizes.call_args.kwargs
        self.assertEqual(set(called_kwargs), {"a", "b"})

    def test_positional_rows_hints_by_column_index_across_all_rows(self) -> None:
        cursor = MagicMock()
        seq = [("short", "short"), ("x" * 32768, "short")]
        _hint_clob_many(cursor, seq, _FakeOracledb())
        cursor.setinputsizes.assert_called_once_with("DB_TYPE_CLOB", None)

    def test_positional_rows_no_hint_when_none_oversized(self) -> None:
        cursor = MagicMock()
        seq = [("short", "short"), ("also", "short")]
        _hint_clob_many(cursor, seq, _FakeOracledb())
        cursor.setinputsizes.assert_not_called()


if __name__ == "__main__":
    unittest.main()
