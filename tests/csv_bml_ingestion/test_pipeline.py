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
    assert (r.status, r.error_code) == ("failed", "CBI_SQL_ARTIFACTS_MISSING") and db.writes() == []


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
    assert r.status == "failed" and r.error_code == "CBI_UNEXPECTED" and "RuntimeError" in r.message and "ORA-boom" not in r.message
    assert db.rolled_back == 1


def test_batch_continues_after_one_bad_file(bml_index, tmp_path):
    db = FakeDb()
    results = [ingest_csv(p, bml_index, db) for p in (None, _seq_csv(tmp_path))]
    assert [r.status for r in results] == ["failed", "loaded"]


# --- ownership: only tables this pipeline created are ever deleted from / loaded -----------------
def test_new_table_is_stamped_with_the_owner_tag(bml_index, tmp_path):
    db = FakeDb()
    assert ingest_csv(_seq_csv(tmp_path), bml_index, db).status == "loaded"
    assert db.comments["ATTRSEQUENCE"] == "csv_bml_ingestion"
    assert ingest_csv(_seq_csv(tmp_path), bml_index, db).status == "loaded"       # owned -> reload allowed


def test_existing_unowned_table_is_refused_before_any_ddl_or_delete(bml_index, tmp_path):
    db = FakeDb()
    db.catalog["ATTRSEQUENCE"] = []                       # exists, no owner comment (e.g. an application table)
    r = ingest_csv(_seq_csv(tmp_path), bml_index, db)
    assert (r.status, r.error_code) == ("failed", "CBI_TABLE_PROTECTED")
    assert "COMMENT ON TABLE attrsequence IS 'csv_bml_ingestion'" in r.message      # how an admin adopts it
    assert not [e for e in db.log if e[0] == "executemany" or (e[0] == "execute" and not e[1].startswith("SELECT"))]


def test_table_owned_by_someone_else_is_refused(bml_index, tmp_path):
    db = FakeDb()
    db.catalog["ATTRSEQUENCE"] = []
    db.comments["ATTRSEQUENCE"] = "csv_bml_ingestion:ws=9"
    assert ingest_csv(_seq_csv(tmp_path), bml_index, db).error_code == "CBI_TABLE_PROTECTED"
    assert ingest_csv(_seq_csv(tmp_path), bml_index, db, owner="csv_bml_ingestion:ws=9").status == "loaded"


def test_admin_adopted_table_is_accepted(bml_index, tmp_path):
    db = FakeDb()
    db.catalog["ATTRSEQUENCE"] = []
    db.comments["ATTRSEQUENCE"] = "csv_bml_ingestion"
    assert ingest_csv(_seq_csv(tmp_path), bml_index, db).status == "loaded"


def test_losing_a_create_race_never_loads_into_the_winners_table(bml_index, tmp_path, monkeypatch):
    """Run A claimed the new table between this run's check and its stamp: refuse, don't overwrite."""
    from aryx.csv_bml_ingestion import pipeline as pl
    db = FakeDb()
    real = pl.require_owned_or_absent

    def stale(factory, table, owner):                      # sees the table as absent ...
        real(factory, table, owner)
        db.catalog["ATTRSEQUENCE"] = []                    # ... then the other run creates and claims it
        db.comments["ATTRSEQUENCE"] = "csv_bml_ingestion:ws=B"
        return False
    monkeypatch.setattr(pl, "require_owned_or_absent", stale)
    r = ingest_csv(_seq_csv(tmp_path), bml_index, db, owner="csv_bml_ingestion:ws=A")
    assert (r.status, r.error_code) == ("failed", "CBI_TABLE_PROTECTED")
    assert db.comments["ATTRSEQUENCE"] == "csv_bml_ingestion:ws=B"                 # winner's tag intact
    assert not [e for e in db.log if e[0] == "executemany" or e[1].startswith("DELETE")]


def test_hand_written_sql_must_pass_the_same_safety_validator(bml_index, tmp_path):
    root = tmp_path / "sql" / "attrsequence"
    root.mkdir(parents=True)
    (root / "schema.sql").write_text("CREATE TABLE IF NOT EXISTS attrsequence (a VARCHAR2(10));\n")
    (root / "indexes.sql").write_text("GRANT ALL ON attrsequence TO PUBLIC;\n")
    db = FakeDb()
    r = ingest_csv(_seq_csv(tmp_path), bml_index, db, sql_root=tmp_path / "sql")
    assert (r.status, r.error_code) == ("failed", "CBI_SQL_UNSAFE")
    assert db.writes() == []


@pytest.mark.parametrize("name", ["gg_messages.csv", "cpq_cache_invalidation_marker.csv"])
def test_other_application_tables_are_denied(name):
    from aryx.csv_bml_ingestion.errors import InvalidTableNameError
    from aryx.csv_bml_ingestion.table_name import extract_table_name
    with pytest.raises(InvalidTableNameError, match="reserved"):
        extract_table_name(name)
