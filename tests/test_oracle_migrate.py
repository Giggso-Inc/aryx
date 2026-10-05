"""Unit tests for oracle_migrate._split_blocks — no live DB required."""
from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import MagicMock, patch


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

from aryx.store.oracle_migrate import _split_blocks  # noqa: E402


class TestSplitBlocksIntegration(unittest.TestCase):
    """Verify _split_blocks against realistic migration file content."""

    def test_idempotent_create_table_block(self) -> None:
        sql = (
            "BEGIN\n"
            "  EXECUTE IMMEDIATE 'CREATE TABLE aryx_entity (\n"
            "    id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY\n"
            "  )';\n"
            "EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;\n"
            "END;\n"
            "/"
        )
        blocks = _split_blocks(sql)
        self.assertEqual(len(blocks), 1)
        self.assertIn("EXECUTE IMMEDIATE", blocks[0])
        self.assertIn("EXCEPTION", blocks[0])

    def test_create_table_plus_index(self) -> None:
        """Two PL/SQL blocks separated by / produce two executable units."""
        sql = (
            "BEGIN\n  EXECUTE IMMEDIATE 'CREATE TABLE t (id NUMBER)';\n"
            "EXCEPTION WHEN OTHERS THEN NULL;\nEND;\n/\n"
            "BEGIN\n  EXECUTE IMMEDIATE 'CREATE INDEX idx_t ON t (id)';\n"
            "EXCEPTION WHEN OTHERS THEN NULL;\nEND;\n/"
        )
        blocks = _split_blocks(sql)
        self.assertEqual(len(blocks), 2)
        self.assertIn("CREATE TABLE", blocks[0])
        self.assertIn("CREATE INDEX", blocks[1])

    def test_noop_migration_select_dual(self) -> None:
        """0010/0016-style no-op migrations produce exactly one block."""
        sql = "-- no-op on Oracle.\nSELECT 1 FROM dual"
        blocks = _split_blocks(sql)
        self.assertEqual(len(blocks), 1)
        self.assertIn("SELECT 1 FROM dual", blocks[0])

    def test_alter_table_after_plsql(self) -> None:
        """Plain ALTER TABLE after the last '/' (no trailing slash) is captured."""
        sql = (
            "BEGIN\n  NULL;\nEND;\n/\n"
            "ALTER TABLE aryx_ontology_type ADD (workspace_id NUMBER(19) DEFAULT 1 NOT NULL);"
        )
        blocks = _split_blocks(sql)
        self.assertEqual(len(blocks), 2)
        self.assertIn("ALTER TABLE", blocks[1])

    def test_declare_block_preserved(self) -> None:
        """DECLARE...BEGIN...END blocks (0027 pattern) stay intact."""
        sql = (
            "DECLARE\n  v_name VARCHAR2(200);\nBEGIN\n"
            "  SELECT constraint_name INTO v_name FROM user_constraints "
            "WHERE ROWNUM = 1;\n"
            "  EXECUTE IMMEDIATE 'ALTER TABLE t DROP CONSTRAINT \"' || v_name || '\"';\n"
            "EXCEPTION WHEN NO_DATA_FOUND THEN NULL;\nEND;\n/"
        )
        blocks = _split_blocks(sql)
        self.assertEqual(len(blocks), 1)
        self.assertIn("DECLARE", blocks[0])
        self.assertIn("NO_DATA_FOUND", blocks[0])

    def test_comment_lines_do_not_produce_blocks(self) -> None:
        sql = "-- Oracle ADB 26ai: survivorship.\n-- workspace survivorship already in 0009.\n"
        blocks = _split_blocks(sql)
        self.assertEqual(len(blocks), 0)

    def test_mixed_graph_schema(self) -> None:
        """graph_schema.sql pattern: 6 table blocks + 4 index blocks + 1 property graph block."""
        sql = "\n/\n".join([
            "BEGIN\n  EXECUTE IMMEDIATE 'CREATE TABLE aryx_graph_vertex (id NUMBER)';\n"
            "EXCEPTION WHEN OTHERS THEN NULL;\nEND;"
        ] * 11) + "\n/"
        blocks = _split_blocks(sql)
        self.assertEqual(len(blocks), 11)

    def test_empty_input(self) -> None:
        self.assertEqual(_split_blocks(""), [])

    def test_whitespace_only_input(self) -> None:
        self.assertEqual(_split_blocks("   \n  \n  "), [])

    def test_single_slash_only(self) -> None:
        self.assertEqual(_split_blocks("/"), [])


# ── apply_oracle_migrations — connect path ────────────────────────────────────

class TestApplyOracleMigrationsConnect(unittest.TestCase):
    """apply_oracle_migrations() credential validation and connect error handling."""

    def _patch_settings(self, db_user: str = "aryx_user",
                        db_password: str = "secret") -> object:
        from aryx.config import Settings
        return Settings(
            _env_file=None,
            oci_adb_dsn="tcps://adb.test.oraclecloud.com:1522/db_high",
            db_user=db_user,
            db_password=db_password,
        )

    def test_raises_when_db_user_missing(self) -> None:
        from aryx.store.oracle_migrate import apply_oracle_migrations
        import aryx.config as cfg_mod
        cfg_mod.get_settings.cache_clear()
        with patch.object(cfg_mod, "get_settings",
                          return_value=self._patch_settings(db_user="")):
            with self.assertRaises(RuntimeError, msg="ARYX_DB_USER"):
                apply_oracle_migrations("tcps://adb.test:1522/db_high")

    def test_raises_when_db_password_missing(self) -> None:
        from aryx.store.oracle_migrate import apply_oracle_migrations
        import aryx.config as cfg_mod
        cfg_mod.get_settings.cache_clear()
        with patch.object(cfg_mod, "get_settings",
                          return_value=self._patch_settings(db_password="")):
            with self.assertRaises(RuntimeError, msg="ARYX_DB_PASSWORD"):
                apply_oracle_migrations("tcps://adb.test:1522/db_high")

    def test_raises_on_connect_failure(self) -> None:
        from aryx.store.oracle_migrate import apply_oracle_migrations
        import aryx.config as cfg_mod
        import oracledb
        cfg_mod.get_settings.cache_clear()
        with patch.object(cfg_mod, "get_settings",
                          return_value=self._patch_settings()), \
             patch.object(oracledb, "connect", create=True,
                          side_effect=Exception("ORA-12541: TNS no listener")):
            with self.assertRaises(RuntimeError, msg="connection failed"):
                apply_oracle_migrations("tcps://adb.test:1522/db_high")

    def test_connect_called_with_user_password_dsn(self) -> None:
        from aryx.store.oracle_migrate import apply_oracle_migrations
        import aryx.config as cfg_mod
        import oracledb
        cfg_mod.get_settings.cache_clear()

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = MagicMock()
        with patch.object(cfg_mod, "get_settings",
                          return_value=self._patch_settings()), \
             patch.object(oracledb, "connect", create=True, return_value=mock_conn) as mock_connect:
            apply_oracle_migrations("tcps://adb.test:1522/db_high")

        mock_connect.assert_called_once_with(
            user="aryx_user", password="secret",
            dsn="tcps://adb.test:1522/db_high",
        )


# ── migration tracking table correctness (PR review M3, 2026-10-04) ─────────
# The tracking table added in this PR must never record a file as "applied"
# when one of its blocks hit a genuine, unexpected error -- only the narrow
# set of known idempotent "already exists/dropped" codes may be marked
# applied despite a block-level warning. And since aryx-api runs 2 uvicorn
# workers that both call apply_oracle_migrations() at startup, the INSERT
# that marks a file applied must tolerate a concurrent duplicate from the
# other worker instead of crashing it out of startup.

class TestMigrationTrackingCorrectness(unittest.TestCase):
    """Exercises apply_oracle_migrations() end to end against a temp
    migrations_oracle/ directory, with a cursor whose execute() behavior is
    driven by the SQL text it's given -- lets each test control exactly
    which blocks "fail" and with what Oracle error code."""

    def _patch_settings(self) -> object:
        from aryx.config import Settings
        return Settings(
            _env_file=None,
            oci_adb_dsn="tcps://adb.test.oraclecloud.com:1522/db_high",
            db_user="aryx_user",
            db_password="secret",
        )

    def _run_with(self, migration_files: dict[str, str], execute_side_effect, *,
                  already_applied: set[str] | dict[str, str | None] | None = None):
        """Write migration_files into a temp dir, run apply_oracle_migrations
        against a mocked connection, return the mock cursor for assertions.

        execute_side_effect(sql) -> None | raises oracledb.Error, applied to
        every cur.execute() call EXCEPT the tracking-table bootstrap/select/
        insert statements, which are handled here so each test only has to
        think about its own migration files' block content.

        already_applied: a set means "already applied, no recorded checksum"
        (None -- the pre-checksum-column row shape); a dict maps filename to
        an explicit recorded checksum string, for checksum-drift tests.
        """
        import tempfile
        from pathlib import Path
        import aryx.config as cfg_mod
        import aryx.store.oracle_migrate as mod
        import oracledb

        cfg_mod.get_settings.cache_clear()
        if already_applied is None:
            already_applied = {}
        elif isinstance(already_applied, set):
            already_applied = {f: None for f in already_applied}

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            for name, content in migration_files.items():
                (tmp_path / name).write_text(content, encoding="utf-8")

            inserted: list[str] = []
            mock_cur = MagicMock()

            def execute(sql, params=None):
                if "CREATE TABLE aryx_schema_migrations" in sql:
                    return
                if sql.strip().upper().startswith("SELECT FILENAME"):
                    return
                if sql.strip().upper().startswith("INSERT INTO ARYX_SCHEMA_MIGRATIONS"):
                    filename = params[0]
                    if filename in inserted:
                        raise oracledb.Error(
                            "ORA-00001: unique constraint violated",
                        )
                    inserted.append(filename)
                    return
                execute_side_effect(sql)

            mock_cur.execute.side_effect = execute
            mock_cur.fetchall.return_value = list(already_applied.items())

            mock_conn = MagicMock()
            mock_conn.cursor.return_value = mock_cur

            with patch.object(cfg_mod, "get_settings", return_value=self._patch_settings()), \
                 patch.object(oracledb, "connect", create=True, return_value=mock_conn), \
                 patch.object(mod, "_ORACLE_MIGRATIONS_DIR", tmp_path):
                mod.apply_oracle_migrations("tcps://adb.test:1522/db_high")

            return mock_cur, inserted

    def test_file_with_only_expected_idempotent_errors_is_marked_applied(self) -> None:
        def side_effect(sql):
            if "DROP" in sql:
                raise __import__("oracledb").Error(
                    "ORA-02443: Cannot drop constraint - nonexistent constraint",
                )

        _cur, inserted = self._run_with(
            {"0001_test.sql": "ALTER TABLE t DROP COLUMN c;"}, side_effect,
        )
        self.assertIn("0001_test.sql", inserted)

    def test_ora_01408_is_treated_as_idempotent_noise_not_unexpected(self) -> None:
        """PR review N3: a plain, un-self-guarded DDL statement hitting
        ORA-01408 (this exact column list is already indexed under a
        different name) must still be marked applied -- several real
        migration files (0039/0041/0042/0045/0047/0049) have a bare
        CREATE INDEX statement that can legitimately hit this."""
        def side_effect(sql):
            raise __import__("oracledb").Error(
                "ORA-01408: such column list already indexed",
            )

        _cur, inserted = self._run_with(
            {"0041_test.sql": "CREATE INDEX idx_t ON t (a, b);"}, side_effect,
        )
        self.assertIn("0041_test.sql", inserted)

    def test_file_with_an_unexpected_error_is_not_marked_applied(self) -> None:
        def side_effect(sql):
            raise __import__("oracledb").Error(
                "ORA-00942: table or view does not exist",
            )

        _cur, inserted = self._run_with(
            {"0002_test.sql": "ALTER TABLE missing_table ADD (x NUMBER);"}, side_effect,
        )
        self.assertNotIn("0002_test.sql", inserted)

    def test_unexpected_failure_in_one_file_does_not_block_later_files(self) -> None:
        def side_effect(sql):
            if "bad_table" in sql:
                raise __import__("oracledb").Error("ORA-00942: table or view does not exist")

        _cur, inserted = self._run_with(
            {
                "0001_bad.sql": "ALTER TABLE bad_table ADD (x NUMBER);",
                "0002_good.sql": "ALTER TABLE good_table ADD (y NUMBER);",
            },
            side_effect,
        )
        self.assertNotIn("0001_bad.sql", inserted)
        self.assertIn("0002_good.sql", inserted)

    def test_concurrent_worker_duplicate_insert_does_not_raise(self) -> None:
        """Two uvicorn workers racing to apply the same new migration: the
        second worker's INSERT hits ORA-00001 and must not crash startup."""
        from aryx.store.oracle_migrate import _mark_applied
        import oracledb

        mock_cur = MagicMock()
        mock_cur.execute.side_effect = oracledb.Error(
            "ORA-00001: unique constraint violated",
        )
        _mark_applied(mock_cur, "0001_test.sql", "deadbeef")  # must not raise

    def test_non_duplicate_error_in_mark_applied_still_raises(self) -> None:
        from aryx.store.oracle_migrate import _mark_applied
        import oracledb

        mock_cur = MagicMock()
        mock_cur.execute.side_effect = oracledb.Error(
            "ORA-00942: table or view does not exist",
        )
        with self.assertRaises(oracledb.Error):
            _mark_applied(mock_cur, "0001_test.sql", "deadbeef")

    def test_already_applied_file_is_skipped_entirely_no_execute(self) -> None:
        def side_effect(sql):
            raise AssertionError(f"should not execute block SQL for an already-applied file: {sql}")

        _cur, inserted = self._run_with(
            {"0001_test.sql": "ALTER TABLE t ADD (z NUMBER);"},
            side_effect,
            already_applied={"0001_test.sql"},
        )
        self.assertEqual(inserted, [])  # not re-inserted either

    # ── PR review round 5, N1: checksum tracking ────────────────────────────

    def test_marks_applied_file_with_its_content_checksum(self) -> None:
        """A newly-applied file's INSERT must carry a real SHA-256 checksum,
        not a placeholder -- the whole point is detecting a later edit."""
        from aryx.store.oracle_migrate import _checksum

        content = "ALTER TABLE t ADD (z NUMBER);"
        captured_params = {}

        def side_effect(sql):
            return

        import aryx.store.oracle_migrate as mod
        import tempfile
        from pathlib import Path
        import aryx.config as cfg_mod
        import oracledb

        cfg_mod.get_settings.cache_clear()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "0001_test.sql").write_text(content, encoding="utf-8")
            mock_cur = MagicMock()

            def execute(sql, params=None):
                if "CREATE TABLE aryx_schema_migrations" in sql:
                    return
                if sql.strip().upper().startswith("SELECT FILENAME"):
                    return
                if sql.strip().upper().startswith("INSERT INTO ARYX_SCHEMA_MIGRATIONS"):
                    captured_params["filename"], captured_params["checksum"] = params
                    return
                side_effect(sql)

            mock_cur.execute.side_effect = execute
            mock_cur.fetchall.return_value = []
            mock_conn = MagicMock()
            mock_conn.cursor.return_value = mock_cur

            with patch.object(cfg_mod, "get_settings", return_value=self._patch_settings()), \
                 patch.object(oracledb, "connect", create=True, return_value=mock_conn), \
                 patch.object(mod, "_ORACLE_MIGRATIONS_DIR", tmp_path):
                mod.apply_oracle_migrations("tcps://adb.test:1522/db_high")

        self.assertEqual(captured_params["filename"], "0001_test.sql")
        self.assertEqual(captured_params["checksum"], _checksum(content))

    def test_unchanged_already_applied_file_skips_quietly_no_drift_warning(self) -> None:
        """Checksum matches the recorded one -- same skip-without-execute
        behavior as before, no drift warning raised."""
        from aryx.store.oracle_migrate import _checksum

        content = "ALTER TABLE t ADD (z NUMBER);"

        def side_effect(sql):
            raise AssertionError(f"should not execute block SQL for an unchanged file: {sql}")

        with patch("aryx.store.oracle_migrate.raven_log") as mock_raven_log:
            _cur, inserted = self._run_with(
                {"0001_test.sql": content}, side_effect,
                already_applied={"0001_test.sql": _checksum(content)},
            )
        self.assertEqual(inserted, [])
        drift_calls = [c for c in mock_raven_log.call_args_list
                      if "CHECKSUM_DRIFT" in str(c)]
        self.assertEqual(drift_calls, [])

    def test_checksum_drift_on_already_applied_file_warns_but_does_not_rerun(self) -> None:
        """PR review round 5, N1: an already-applied file whose content has
        since changed must be loudly warned about (raven_log ERROR,
        ARYX_MIGRATE_CHECKSUM_DRIFT) but NOT re-executed -- re-running an
        edited migration automatically could be wrong if it isn't
        idempotent."""
        def side_effect(sql):
            raise AssertionError(f"must not execute blocks for a drifted file: {sql}")

        with patch("aryx.store.oracle_migrate.raven_log") as mock_raven_log:
            _cur, inserted = self._run_with(
                {"0001_test.sql": "ALTER TABLE t ADD (z NUMBER);"},  # current content
                side_effect,
                already_applied={"0001_test.sql": "stale-checksum-from-before-the-edit"},
            )

        self.assertEqual(inserted, [])  # not re-inserted
        drift_calls = [c for c in mock_raven_log.call_args_list
                      if c.kwargs.get("error_code") == "ARYX_MIGRATE_CHECKSUM_DRIFT"]
        self.assertEqual(len(drift_calls), 1)
        self.assertEqual(drift_calls[0].kwargs["context"]["file"], "0001_test.sql")

    def test_pre_checksum_row_with_none_recorded_is_not_treated_as_drift(self) -> None:
        """A row written before the checksum column existed has
        recorded=None -- must skip quietly like before, not fire a false
        drift warning for every pre-existing migration on the first boot
        after this ships."""
        def side_effect(sql):
            raise AssertionError("should not execute blocks for an already-applied file")

        with patch("aryx.store.oracle_migrate.raven_log") as mock_raven_log:
            _cur, inserted = self._run_with(
                {"0001_test.sql": "ALTER TABLE t ADD (z NUMBER);"}, side_effect,
                already_applied={"0001_test.sql": None},
            )

        self.assertEqual(inserted, [])
        drift_calls = [c for c in mock_raven_log.call_args_list
                      if "CHECKSUM_DRIFT" in str(c)]
        self.assertEqual(drift_calls, [])

    def test_ensure_tracking_table_adds_checksum_column_to_pre_existing_table(self) -> None:
        """_ensure_tracking_table must fall back to ALTER TABLE ADD
        (checksum) when CREATE TABLE fails because the table already
        exists from before the checksum column was added."""
        from aryx.store.oracle_migrate import _ensure_tracking_table
        import oracledb

        calls = []
        mock_cur = MagicMock()

        def execute(sql, params=None):
            calls.append(sql)
            if "CREATE TABLE aryx_schema_migrations" in sql:
                raise oracledb.Error("ORA-00955: name is already used by an existing object")
            # ALTER TABLE ADD (checksum ...) succeeds this time
            return

        mock_cur.execute.side_effect = execute
        _ensure_tracking_table(mock_cur)

        self.assertTrue(any("ALTER TABLE aryx_schema_migrations" in c for c in calls))

    def test_ensure_tracking_table_tolerates_checksum_column_already_present(self) -> None:
        """A boot after the column was already added by an earlier boot
        must not raise on ORA-01430 (column already exists)."""
        from aryx.store.oracle_migrate import _ensure_tracking_table
        import oracledb

        def execute(sql, params=None):
            if "CREATE TABLE aryx_schema_migrations" in sql:
                raise oracledb.Error("ORA-00955: name is already used by an existing object")
            raise oracledb.Error("ORA-01430: column being added already exists in table")

        mock_cur = MagicMock()
        mock_cur.execute.side_effect = execute
        _ensure_tracking_table(mock_cur)  # must not raise


if __name__ == "__main__":
    unittest.main()
