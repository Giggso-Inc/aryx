"""Regressions for the PR #418 review: complete rejects download, owner stamp before indexes,
rejected-row files removed with the workspace, spreadsheet-safe cells, unwritable rejects folder."""
from __future__ import annotations

from aryx.csv_bml_ingestion import ingest_csv
from aryx.csv_bml_ingestion.overflow import _RejectsWriter
from aryx.csv_bml_ingestion.rejects import RejectedRow, csv_safe_cell
from aryx.csv_bml_ingestion.workspace_tables import remove_workspace_files

from .conftest import FakeCursor, FakeDb
from .test_issues import client, seeded_run  # noqa: F401  (fixture)
from .test_pipeline import _seq_csv


def test_rejects_download_is_not_cut_at_500_rows(client):  # noqa: F811
    rows = [RejectedRow(i, "CBI_VALUE_TOO_LONG", "too long", {"columns": {"name": f"v{i}", "qty": i}})
            for i in range(2, 1202)]
    run_id = seeded_run(client.db, ws=3, rows=rows)
    r = client.get(f"/admin/csv-bml/runs/{run_id}/rejects.csv", params={"workspace_id": 3})
    assert len(r.text.splitlines()) == 1 + 1200                     # header + every stored row


def test_a_failed_index_does_not_leave_a_table_the_pipeline_then_refuses(bml_index, tmp_path, monkeypatch):
    db = FakeDb()
    real = FakeCursor.execute

    def boom(self, sql, params=None):
        if sql.startswith("CREATE INDEX"):
            raise RuntimeError("ORA-00955: name is already used")
        return real(self, sql, params)
    monkeypatch.setattr(FakeCursor, "execute", boom)
    first = ingest_csv(_seq_csv(tmp_path), bml_index, db)
    assert first.status == "failed"
    assert db.comments["ATTRSEQUENCE"] == "csv_bml_ingestion"       # already ours: DDL had auto-committed
    monkeypatch.setattr(FakeCursor, "execute", real)
    second = ingest_csv(_seq_csv(tmp_path), bml_index, db)
    assert (second.status, second.error_code) == ("loaded", "")      # not CBI_TABLE_PROTECTED


def test_rejected_row_files_go_with_the_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("ARYX_CSV_BML_SQL_DIR", str(tmp_path))
    for ws in (7, 70, 9):
        (tmp_path / f"ws_{ws}" / "_rejects").mkdir(parents=True)
        (tmp_path / f"ws_{ws}" / "_rejects" / "t.rejects.csv").write_text("secret")
        (tmp_path / f"ws_{ws}" / "tbl").mkdir()
    (tmp_path / "not_a_workspace").mkdir()
    remove_workspace_files(7, whole_workspace=False)                 # data purge: rejects only, SQL kept
    assert not (tmp_path / "ws_7" / "_rejects").exists() and (tmp_path / "ws_7" / "tbl").exists()
    assert (tmp_path / "ws_70" / "_rejects").exists()                # ws7 never matches ws70
    remove_workspace_files(7, whole_workspace=True)                  # delete: the whole workspace folder
    assert not (tmp_path / "ws_7").exists() and (tmp_path / "ws_9").exists()
    remove_workspace_files(None, whole_workspace=True)               # factory reset
    assert not (tmp_path / "ws_70").exists() and not (tmp_path / "ws_9").exists()
    assert (tmp_path / "not_a_workspace").exists()                   # only ws_<digits> folders are touched


def test_cells_starting_with_tab_or_cr_are_formula_safe_too():
    assert csv_safe_cell("\t=1+1") == "'\t=1+1" and csv_safe_cell("\r=1") == "'\r=1"
    assert csv_safe_cell("plain") == "plain" and csv_safe_cell(None) == ""


def test_an_unwritable_rejects_folder_does_not_fail_the_load(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")                                           # a file where the folder should be
    w = _RejectsWriter(blocker / "sub" / "t.rejects.csv", ["a"])
    w.write(("x",), "too long")                                       # must not raise
    w.write(("y",), "too long")
    w.close()
    assert w.path is None
