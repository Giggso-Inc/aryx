"""Per-workspace table names: ws<id>_<file stem>; step 2 keeps using the logical name."""
from __future__ import annotations

import pytest

from aryx.csv_bml_ingestion import ingest_csv
from aryx.csv_bml_ingestion.errors import InvalidTableNameError, SqlUnsafeError
from aryx.csv_bml_ingestion.table_naming import is_workspace_table, physical_table, rename_statements

from .conftest import FakeDb
from .test_pipeline import _seq_csv


def test_physical_name_is_prefixed_with_the_workspace_id():
    assert physical_table("attrsequence", 7) == "ws7_attrsequence"
    assert physical_table("attrsequence", 12345) == "ws12345_attrsequence"


def test_a_name_that_no_longer_fits_is_refused_with_a_clear_message():
    with pytest.raises(InvalidTableNameError, match="too long once the workspace prefix"):
        physical_table("a" * 62, 7)
    assert physical_table("a" * 58, 7).startswith("ws7_")                  # still fits


def test_is_workspace_table_is_exact_about_the_id():
    assert is_workspace_table("ws7_attrsequence", 7) and is_workspace_table("WS7_ATTRSEQUENCE", 7)
    assert not is_workspace_table("ws70_attrsequence", 7)                  # workspace 70 is not workspace 7
    assert not is_workspace_table("attrsequence", 7) and not is_workspace_table("ws7attr", 7)


STMTS = (
    "CREATE TABLE IF NOT EXISTS attrsequence ( update_action VARCHAR2(50), attrsequence VARCHAR2(10) )",
    "CREATE INDEX IF NOT EXISTS idx_attrsequence_cpq_attr ON attrsequence (cpqmodel, attrsequence)",
)


def test_rename_swaps_only_the_table_and_index_names():
    out = rename_statements(STMTS, "attrsequence", "ws7_attrsequence")
    assert out[0] == "CREATE TABLE IF NOT EXISTS ws7_attrsequence ( update_action VARCHAR2(50), attrsequence VARCHAR2(10) )"
    assert out[1] == "CREATE INDEX IF NOT EXISTS idx_ws7_attrsequence_cpq_attr ON ws7_attrsequence (cpqmodel, attrsequence)"


def test_rename_is_a_no_op_for_the_same_name_and_refuses_anything_unexpected():
    assert rename_statements(STMTS, "attrsequence", "attrsequence") == STMTS
    with pytest.raises(SqlUnsafeError):
        rename_statements(("GRANT ALL ON attrsequence TO PUBLIC",), "attrsequence", "ws7_attrsequence")


def test_pipeline_uses_the_logical_name_for_step_2_and_the_physical_name_afterwards(bml_index, tmp_path):
    db = FakeDb()
    seen = []

    def namer(logical):
        seen.append(logical)
        return f"ws9_{logical}"
    r = ingest_csv(_seq_csv(tmp_path), bml_index, db, physical_table=namer)
    assert r.status == "loaded" and r.table == "attrsequence" and r.physical_table == "ws9_attrsequence"
    assert seen == ["attrsequence"]                                        # called once, with the logical name
    assert r.bml_scripts == ["id=111"]                                     # step 2 matched the logical name
    ddl = [e[1] for e in db.statements("execute")]
    assert any(s.startswith("CREATE TABLE IF NOT EXISTS ws9_attrsequence") for s in ddl)
    assert any("idx_ws9_attrsequence_" in s and "ON ws9_attrsequence" in s for s in ddl)
    assert db.comments == {"WS9_ATTRSEQUENCE": "csv_bml_ingestion"}


def test_a_name_that_is_too_long_fails_cleanly_before_any_sql(bml_index, tmp_path):
    db = FakeDb()
    r = ingest_csv(_seq_csv(tmp_path), bml_index, db, physical_table=lambda t: physical_table("a" * 62, 7))
    assert (r.status, r.error_code) == ("failed", "CBI_TABLE_NAME_INVALID") and db.log == []


def test_default_keeps_the_logical_name_so_the_cli_is_unchanged(bml_index, tmp_path):
    db = FakeDb()
    r = ingest_csv(_seq_csv(tmp_path), bml_index, db)
    assert r.physical_table == "attrsequence" and "ATTRSEQUENCE" in db.comments


# --- workspace delete / purge / nuke drop the workspace's own tables, and only those
class CatalogDb:
    """Answers the ownership query and records DDL; just enough for workspace_tables."""

    def __init__(self, tables):
        self.tables, self.log = dict(tables), []

    def __call__(self):
        from contextlib import contextmanager

        db = self

        class Cur:
            def execute(self, sql, params=None):
                db.log.append(sql)
                self._rows = [(n.upper(), c) for n, c in db.tables.items() if params and c.startswith(params[0])] \
                    if sql.startswith("SELECT") else []
                if sql.startswith("DROP TABLE"):
                    db.tables.pop(sql.split()[2].lower(), None)

            def fetchall(self):
                return self._rows

        @contextmanager
        def ctx():
            yield type("C", (), {"cursor": lambda self: Cur()})()
        return ctx()


TABLES = {
    "ws7_attrsequence": "csv_bml_ingestion:ws=7", "ws7_other": "csv_bml_ingestion:ws=7",
    "ws70_attrsequence": "csv_bml_ingestion:ws=70",          # a different workspace whose id starts with 7
    "ws9_attrsequence": "csv_bml_ingestion:ws=9",
    "attrsequence": "csv_bml_ingestion:ws=7",                # legacy, pre-per-workspace table: never dropped
    "ws7_misowned": "someone-else",                          # right name, wrong owner tag: never dropped
    "aryx_workspace": "csv_bml_ingestion:ws=7",              # tag copied onto an app table: name does not match
}


def test_deleting_a_workspace_drops_only_its_own_tables():
    from aryx.csv_bml_ingestion.workspace_tables import drop_workspace_tables
    db = CatalogDb(TABLES)
    assert sorted(drop_workspace_tables(db, 7)) == ["ws7_attrsequence", "ws7_other"]
    assert sorted(db.tables) == sorted(set(TABLES) - {"ws7_attrsequence", "ws7_other"})


def test_a_factory_reset_drops_every_workspace_table_and_still_spares_everything_else():
    from aryx.csv_bml_ingestion.workspace_tables import drop_workspace_tables
    db = CatalogDb(TABLES)
    assert sorted(drop_workspace_tables(db, None)) == ["ws70_attrsequence", "ws7_attrsequence", "ws7_other", "ws9_attrsequence"]
    assert sorted(db.tables) == ["aryx_workspace", "attrsequence", "ws7_misowned"]


def test_workspace_store_cleanup_runs_both_steps_and_never_raises(monkeypatch):
    from types import SimpleNamespace
    from aryx.store.oracle_workspace import OracleWorkspaceStore
    calls = []
    monkeypatch.setattr("aryx.csv_bml_ingestion.issue_store.purge_issues", lambda f, w: calls.append(("issues", w)))
    monkeypatch.setattr("aryx.csv_bml_ingestion.workspace_tables.drop_workspace_tables",
                        lambda f, w: (_ for _ in ()).throw(RuntimeError("ORA-00942")))
    store = OracleWorkspaceStore.__new__(OracleWorkspaceStore)
    store._pool = SimpleNamespace(connection=lambda: None)
    store._purge_csv_issues(7)                                  # the failing table drop is swallowed, issues were still cleaned
    assert calls == [("issues", 7)]
