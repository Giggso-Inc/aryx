"""End-to-end pipeline tests against a fake DB, including every negative flow."""
from __future__ import annotations

import pytest

from aryx.csv_bml_ingestion import ingest_csv
from aryx.csv_bml_ingestion.csv_reader import read_layout

from .conftest import FakeDb, write_csv

SEQ_HEADER = ["_update_action", "key", "CPQModel", "BaseModel", "attr1", "val1", "AttrName", "Seq",
              "optionOrReqFlag", "startDate", "endDate", "createdDate", "createdBy", "updatedDate",
              "updatedBy"]


def _seq_csv(tmp_path, name="attrSequence.csv", rows=None):
    rows = rows if rows is not None else [
        ["modify", "k1", "M1", "B1", "", "", "attrA", "1", "R", "", "", "", "", "", ""],
        ["modify", "k2", "M1", "B1", "", "", "attrB", "2", "O", "", "", "", "", "", ""],
        ["modify", "k3", "M2", "B1", "", "", "attrC", "3", "O", "", "", "", "", "", ""],
    ]
    return write_csv(tmp_path / name, SEQ_HEADER, ["String"] * 15, rows)


def test_happy_path_mixed_case_filename(bml_index, tmp_path):
    db = FakeDb()
    r = ingest_csv(_seq_csv(tmp_path, "AttrSequence.csv"), bml_index, db)
    assert (r.status, r.table, r.rows_loaded, r.rows_bad, r.error_code) == ("loaded", "attrsequence", 3, 0, "")
    assert r.bml_scripts == ["id=111"]
    ddl = [e[1] for e in db.statements("execute")]
    assert ddl[0].startswith("DELETE") is False  # DDL runs first, in its own connection
    assert any(s.startswith("CREATE TABLE IF NOT EXISTS attrsequence") for s in ddl)
    assert sum(s.startswith("CREATE INDEX") for s in ddl) == 2
    assert "DELETE FROM attrsequence" in ddl
    ins = db.statements("executemany")[0]
    assert ins[1].startswith("INSERT INTO attrsequence (update_action, key, cpqmodel")
    assert ins[1].count("%s") == 15 and len(ins[2]) == 3
    assert db.rolled_back == 0


def test_replace_false_does_not_delete(bml_index, tmp_path):
    db = FakeDb()
    ingest_csv(_seq_csv(tmp_path), bml_index, db, replace=False)
    assert "DELETE FROM attrsequence" not in [e[1] for e in db.statements("execute")]


def test_batching(bml_index, tmp_path):
    rows = [["modify", f"k{i}", "M", "B", "", "", "a", str(i), "R", "", "", "", "", "", ""] for i in range(25)]
    db = FakeDb()
    r = ingest_csv(_seq_csv(tmp_path, rows=rows), bml_index, db, batch_size=10)
    assert r.rows_loaded == 25
    assert [len(e[2]) for e in db.statements("executemany")] == [10, 10, 5]


def test_table_name_missing_is_handled_not_raised(bml_index):
    db = FakeDb()
    for bad in (None, "", "   "):
        r = ingest_csv(bad, bml_index, db)
        assert r.status == "failed" and r.error_code == "CBI_TABLE_NAME_MISSING"
    assert db.log == []


def test_unsafe_table_name_rejected_before_any_sql(bml_index, tmp_path):
    p = write_csv(tmp_path / "x;drop table y.csv", ["a"], ["String"], [["1"]])
    db = FakeDb()
    r = ingest_csv(p, bml_index, db)
    assert r.status == "failed" and r.error_code == "CBI_TABLE_NAME_INVALID" and db.log == []


def test_no_bml_query_is_skipped_and_logged(bml_index, tmp_path):
    p = write_csv(tmp_path / "ar1Matrix.csv", ["countryCode"], ["String"], [["US"]])
    db = FakeDb()
    r = ingest_csv(p, bml_index, db)
    assert (r.status, r.error_code, r.table) == ("skipped", "CBI_BML_NOT_FOUND", "ar1matrix")
    assert db.log == []


def test_near_miss_table_still_not_ingested(bml_index, tmp_path):
    p = write_csv(tmp_path / "attrToPart.csv", ["a"], ["String"], [["1"]])
    r = ingest_csv(p, bml_index, FakeDb())
    assert r.status == "skipped" and r.error_code == "CBI_BML_NOT_FOUND"


def test_bml_found_but_sql_files_missing(bml_index, tmp_path):
    db = FakeDb()
    r = ingest_csv(_seq_csv(tmp_path), bml_index, db, sql_root=tmp_path / "empty")
    assert (r.status, r.error_code) == ("failed", "CBI_SQL_ARTIFACTS_MISSING") and db.log == []


def test_bad_rows_counted_but_load_succeeds(bml_index, tmp_path):
    rows = [["modify", "k", "M", "B", "", "", "a", "1", "R", "", "", "", "", "", ""], ["short"]]
    r = ingest_csv(_seq_csv(tmp_path, rows=rows), bml_index, FakeDb())
    assert (r.status, r.rows_loaded, r.rows_bad) == ("loaded", 1, 1)


def test_malformed_csv_layout_fails_gracefully(bml_index, tmp_path):
    p = tmp_path / "attrSequence.csv"
    p.write_text("a,b\n1,2\n", encoding="utf-8")
    r = ingest_csv(p, bml_index, FakeDb())
    assert (r.status, r.error_code) == ("failed", "CBI_CSV_FORMAT")


def test_db_failure_rolls_back_and_reports(bml_index, tmp_path):
    db = FakeDb(fail_on="INSERT INTO")
    r = ingest_csv(_seq_csv(tmp_path), bml_index, db)
    assert r.status == "failed" and r.error_code == "CBI_UNEXPECTED" and "ORA-boom" in r.message
    assert db.rolled_back == 1


def test_batch_continues_after_one_bad_file(bml_index, tmp_path):
    db = FakeDb()
    results = [ingest_csv(p, bml_index, db) for p in (None, _seq_csv(tmp_path))]
    assert [r.status for r in results] == ["failed", "loaded"]
