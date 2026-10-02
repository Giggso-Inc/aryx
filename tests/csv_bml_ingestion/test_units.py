"""Unit tests: table name, BMQL parsing, BML index, CSV reader, SQL catalog."""
from __future__ import annotations

import re

import pytest

from aryx.csv_bml_ingestion.bmql import extract_queries, strip_comments
from aryx.csv_bml_ingestion.constants import SQL_ROOT
from aryx.csv_bml_ingestion.csv_reader import CsvStats, iter_rows, read_layout, to_column_name
from aryx.csv_bml_ingestion.errors import (
    CsvFormatError, InvalidTableNameError, SqlArtifactsMissingError, TableNameMissingError, XmlSourceError,
)
from aryx.csv_bml_ingestion.bml_index import BmlIndex
from aryx.csv_bml_ingestion.sql_catalog import load_sql_artifacts, split_statements
from aryx.csv_bml_ingestion.table_name import extract_table_name

from .conftest import write_csv


# --- step 1 -----------------------------------------------------------------
@pytest.mark.parametrize("name,expected", [
    ("attrToPart.csv", "attrtopart"), ("C:/x/AttrSequence.CSV", "attrsequence"),
    ("ar1Matrix.csv", "ar1matrix"), ("plain", "plain"),
])
def test_table_name_lowercased_stem(name, expected):
    assert extract_table_name(name) == expected


@pytest.mark.parametrize("bad", [None, "", "   ", ".csv"])
def test_table_name_missing(bad):
    with pytest.raises(TableNameMissingError):
        extract_table_name(bad)


@pytest.mark.parametrize("bad", ["my table.csv", "a-b.csv", "1abc.csv", "x;drop.csv"])
def test_table_name_unsafe(bad):
    with pytest.raises(InvalidTableNameError):
        extract_table_name(bad)


# --- BMQL parsing -----------------------------------------------------------
def test_comments_stripped_but_strings_kept():
    out = strip_comments('a = "http://x"; // BMQL("SELECT 1 FROM t")\n/* BMQL("SELECT 2 FROM u") */ b=1;')
    assert "http://x" in out and "SELECT 1" not in out and "SELECT 2" not in out


def test_extract_queries_literal_variable_concat_and_skips_dynamic():
    script = '''v = "tblA"; w = "tblB";
x = BMQL("select a from $v where b=1");
y = bmql("select a " + "from literalT where c=2");
z = BMQL(someVar);
q = BMQL("select a from $unknown");'''
    qs = extract_queries(script)
    assert [q.tables for q in qs] == [("tblA",), ("literalT",), ()]


def test_variable_with_multiple_literal_assignments_yields_all_candidates():
    qs = extract_queries('t = "one"; if(c){ t = "two"; } BMQL("select * from $t");')
    assert qs[0].tables == ("one", "two")


# --- step 2 -----------------------------------------------------------------
def test_index_matches_case_insensitively(bml_index):
    for name in ("attrSequence", "ATTRSEQUENCE", "attrsequence"):
        r = bml_index.lookup(name)
        assert len(r.matches) == 1
        m = r.matches[0]
        assert (m.script_id, m.script_guid, m.java_class_name) == ("111", "guid-111", "com.bm.Action_111")
        assert "ORDER BY Seq" in m.queries[0].sql


def test_index_literal_concat_table_and_commented_query_ignored(bml_index):
    assert bml_index.lookup("attrToPDNonFrequency").matches
    assert "commentedout" not in bml_index.tables


def test_index_exact_match_only_reports_near_misses(bml_index):
    r = bml_index.lookup("attrToPart")
    assert r.matches == () and r.near_misses == ("attrtopart_pcrdev",)
    assert bml_index.lookup("ar1Matrix").matches == ()


def test_bad_xml_raises_typed_error():
    with pytest.raises(XmlSourceError):
        BmlIndex.from_xml_bytes(b"<not-closed>")
    with pytest.raises(XmlSourceError):
        BmlIndex.from_xml_file("/nonexistent/file.xml")


# --- CSV reader ---------------------------------------------------------------
def test_column_names():
    assert to_column_name("_update_action") == "update_action"
    assert to_column_name("CPQModel") == "cpqmodel"
    assert to_column_name("date") == "date_col"
    assert to_column_name("1st") == "c_1st"
    with pytest.raises(CsvFormatError):
        to_column_name("___")


def test_reader_converts_types_and_counts_bad_rows(tmp_path):
    p = write_csv(tmp_path / "t.csv", ["_update_action", "Seq", "Name"], ["String", "Integer", "String"],
                  [["modify", "1", "a"], ["modify", "x", "b"], ["modify", "", ""], ["too", "few"]])
    layout = read_layout(p)
    assert layout.columns == ("update_action", "seq", "name")
    stats = CsvStats()
    rows = list(iter_rows(p, layout, stats))
    assert rows == [("modify", 1, "a"), ("modify", None, None)]
    assert (stats.rows_read, stats.rows_bad) == (4, 2)


@pytest.mark.parametrize("content", ["", "a,b\n1,2\n", "_start meta data\nA\nString\n"])
def test_reader_rejects_bad_layout(tmp_path, content):
    p = tmp_path / "bad.csv"
    p.write_text(content, encoding="utf-8")
    with pytest.raises(CsvFormatError):
        read_layout(p)


# --- step 3 (runtime side) ------------------------------------------------------
def test_split_statements():
    sql = "-- c\nCREATE TABLE t (\n a VARCHAR2(5)\n);\n\nCREATE INDEX i\n ON t (a);\n"
    assert split_statements(sql) == ("CREATE TABLE t ( a VARCHAR2(5) )", "CREATE INDEX i ON t (a)")


def test_missing_sql_artifacts(tmp_path):
    with pytest.raises(SqlArtifactsMissingError):
        load_sql_artifacts("nothere", tmp_path)


def _committed_tables() -> list[str]:
    return sorted(p.name for p in SQL_ROOT.iterdir() if p.is_dir())


@pytest.mark.parametrize("table", _committed_tables())
def test_committed_sql_is_well_formed(table):
    """Each committed table: one CREATE TABLE, indexes only reference real columns, files present."""
    art = load_sql_artifacts(table)
    assert len(art.schema_statements) == 1
    create = art.schema_statements[0]
    assert re.match(rf"CREATE TABLE IF NOT EXISTS {table} \(", create)
    cols = [c.strip().split()[0] for c in re.search(r"\((.*)\)\s*$", create).group(1).split(",\n") or []]
    cols = re.findall(r"(\w+) (?:VARCHAR2|NUMBER)\(", create)
    assert cols and len(cols) == len(set(cols))
    assert (art.directory / "bml_source.md").is_file()
    for idx in art.index_statements:
        m = re.match(rf"CREATE INDEX IF NOT EXISTS idx_{table}_\w+ ON {table} \(([\w, ]+)\)$", idx)
        assert m, idx
        assert {c.strip() for c in m.group(1).split(",")} <= set(cols)
