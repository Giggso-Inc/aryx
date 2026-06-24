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
        sql = "-- Oracle ADB 23ai: survivorship.\n-- workspace survivorship already in 0009.\n"
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
             patch.object(oracledb, "connect",
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
             patch.object(oracledb, "connect", return_value=mock_conn) as mock_connect:
            apply_oracle_migrations("tcps://adb.test:1522/db_high")

        mock_connect.assert_called_once_with(
            user="aryx_user", password="secret",
            dsn="tcps://adb.test:1522/db_high",
        )


if __name__ == "__main__":
    unittest.main()
