"""Over-length / overflow handling: reject, truncate, fail, bytes vs chars, numbers, schema mismatch."""
from __future__ import annotations

import csv

import pytest

from aryx.csv_bml_ingestion import ingest_csv
from aryx.csv_bml_ingestion.column_limits import ColumnLimit
from aryx.csv_bml_ingestion.overflow import OverflowPolicy, OverflowReport, guard_rows

from .conftest import FakeDb
from .test_pipeline import _seq_csv


def _row(cpqmodel: str, seq: str = "1") -> list[str]:
    return ["modify", "k", cpqmodel, "B", "", "", "attr", seq, "R", "", "", "", "", "", ""]


def test_reject_skips_row_writes_rejects_file_and_loads_rest(bml_index, tmp_path):
    p = _seq_csv(tmp_path, rows=[_row("ok"), _row("x" * 1001), _row("fine")])
    db = FakeDb()
    r = ingest_csv(p, bml_index, db)
    assert (r.status, r.rows_loaded, r.rows_rejected, r.rows_truncated) == ("loaded", 2, 1, 0)
    assert r.rejects_file.endswith("attrsequence.rejects.csv")
    rows = list(csv.reader(open(r.rejects_file, encoding="utf-8")))
    assert rows[0][-1] == "reject_reason" and "cpqmodel: 1001 bytes > limit 1000" in rows[1][-1]
    assert rows[1][2] == "x" * 1001  # the full original value is preserved for re-processing


def test_no_rejects_file_when_everything_fits(bml_index, tmp_path):
    r = ingest_csv(_seq_csv(tmp_path), bml_index, FakeDb())
    assert r.rows_rejected == 0 and r.rejects_file == ""
    assert not list(tmp_path.glob("*.rejects.csv"))


def test_truncate_cuts_to_limit(bml_index, tmp_path):
    db = FakeDb()
    r = ingest_csv(_seq_csv(tmp_path, rows=[_row("y" * 1500)]), bml_index, db, overflow=OverflowPolicy.TRUNCATE)
    assert (r.rows_loaded, r.rows_truncated, r.rows_rejected) == (1, 1, 0)
    loaded = db.statements("executemany")[0][2][0]
    assert loaded[2] == "y" * 1000


def test_fail_policy_aborts_and_rolls_back(bml_index, tmp_path):
    db = FakeDb()
    r = ingest_csv(_seq_csv(tmp_path, rows=[_row("ok"), _row("z" * 2000)]), bml_index, db,
                   overflow=OverflowPolicy.FAIL)
    assert (r.status, r.error_code) == ("failed", "CBI_VALUE_TOO_LONG")
    assert db.rolled_back == 1


def test_limit_is_in_bytes_for_multibyte_text():
    rep = OverflowReport()
    limits = {"c": ColumnLimit("text", max_bytes=10)}
    # 4 chars x 3 bytes = 12 bytes > 10 although only 4 characters
    out = list(guard_rows([("€€€€",)], ["c"], limits, OverflowPolicy.TRUNCATE, rep, rejects_path=None))  # type: ignore[arg-type]
    assert out == [("€€€",)] and len(out[0][0].encode()) == 9  # cut on a character boundary, not mid-char


def test_char_semantics_column_counts_characters():
    rep = OverflowReport()
    limits = {"c": ColumnLimit("text", max_chars=4)}
    ok = list(guard_rows([("€€€€",)], ["c"], limits, OverflowPolicy.FAIL, rep, rejects_path=None))  # type: ignore[arg-type]
    assert ok == [("€€€€",)]


def test_number_overflow_is_rejected_even_under_truncate(tmp_path):
    rep = OverflowReport()
    limits = {"n": ColumnLimit("number", digits=3), "t": ColumnLimit("text", max_bytes=2)}
    rows = [(1234, "ab"), (12, "abcdef")]
    out = list(guard_rows(rows, ["n", "t"], limits, OverflowPolicy.TRUNCATE, rep, tmp_path / "r.csv"))
    assert out == [(12, "ab")]
    assert (rep.rows_rejected, rep.rows_truncated) == (1, 1)


def test_none_values_never_violate(tmp_path):
    rep = OverflowReport()
    out = list(guard_rows([(None,)], ["c"], {"c": ColumnLimit("text", max_bytes=1)}, OverflowPolicy.FAIL, rep,
                          tmp_path / "r.csv"))
    assert out == [(None,)]


def test_csv_column_missing_from_table_is_schema_mismatch(bml_index, tmp_path):
    from .conftest import write_csv
    p = write_csv(tmp_path / "attrToPDNonFrequency.csv", ["_update_action", "cpqModel", "brandNewColumn"],
                  ["String"] * 3, [["modify", "m", "x"]])
    r = ingest_csv(p, bml_index, FakeDb())
    assert (r.status, r.error_code) == ("failed", "CBI_SCHEMA_MISMATCH") and "brandnewcolumn" in r.message


def test_rejects_file_neutralises_formulas_and_is_not_stale(tmp_path):
    path = tmp_path / "r.csv"
    limits = {"c": ColumnLimit("text", max_bytes=2)}
    list(guard_rows([("=cmd|x",), ("ok",)], ["c"], limits, OverflowPolicy.REJECT, OverflowReport(), path))
    assert list(csv.reader(open(path, encoding="utf-8")))[1][0] == "'=cmd|x"
    list(guard_rows([("ok",)], ["c"], limits, OverflowPolicy.REJECT, OverflowReport(), path))
    assert not path.exists()  # a clean re-run removes the previous run's rejects


def test_malformed_csv_runs_no_ddl(bml_index, tmp_path):
    p = tmp_path / "attrSequence.csv"
    p.write_text("a,b\n1,2\n", encoding="utf-8")
    db = FakeDb()
    r = ingest_csv(p, bml_index, db)
    assert r.error_code == "CBI_CSV_FORMAT" and db.log == []
