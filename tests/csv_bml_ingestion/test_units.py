"""Unit tests: table name, BMQL parsing, BML index, CSV reader, SQL catalog."""
from __future__ import annotations

import re

import pytest

from aryx.csv_bml_ingestion.query_extract import extract_queries, strip_comments
from aryx.csv_bml_ingestion.constants import default_sql_root
from aryx.csv_bml_ingestion.sql_validate import ColumnSpec, validate_indexes, validate_schema
from aryx.csv_bml_ingestion.csv_reader import CsvStats, iter_rows, read_layout, to_column_name
from aryx.csv_bml_ingestion.errors import (
    CsvFormatError, InvalidTableNameError, SqlArtifactsMissingError, TableNameMissingError, XmlSourceError,
)
from aryx.csv_bml_ingestion.bml_index import BmlIndex
from aryx.csv_bml_ingestion.sql_catalog import load_sql_artifacts, split_statements
from aryx.csv_bml_ingestion.table_name import extract_table_name

from .conftest import FIXTURE_SQL, write_csv


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
        assert m.identity == {"id": "111", "guid": "guid-111", "java_class_name": "com.bm.Action_111"}
        assert (m.label, m.node_tag, m.prop) == ("id=111", "script_text", "text")
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


def _fixture_tables() -> list[str]:
    return sorted(p.name for p in FIXTURE_SQL.iterdir() if p.is_dir())


@pytest.mark.parametrize("table", _fixture_tables())
def test_agent_authored_sql_passes_the_strict_validator(table, seeded_sql_root):
    """Real agent-authored SQL must satisfy the same validator that gates run-time LLM output."""
    art = load_sql_artifacts(table)
    cols = re.findall(r"(\w+) (VARCHAR2|NUMBER)\(", art.schema_statements[0])
    specs = [ColumnSpec(c.lower(), "text" if t == "VARCHAR2" else "number") for c, t in cols]
    sizes = validate_schema(art.schema_statements[0] + ";", table, specs)
    index_sql = "\n".join(s + ";" for s in art.index_statements)
    assert validate_indexes(index_sql, table, sizes) == len(art.index_statements)
    assert (art.directory / "bml_source.md").is_file()


def test_sql_root_default_and_env_override(monkeypatch, tmp_path):
    monkeypatch.delenv("ARYX_CSV_BML_SQL_DIR", raising=False)
    assert default_sql_root().name == "sql" and default_sql_root().parent.name == "csv_bml_ingestion"
    monkeypatch.setenv("ARYX_CSV_BML_SQL_DIR", str(tmp_path))
    assert default_sql_root() == tmp_path


# --- step 2 is structure- and language-agnostic ---------------------------------
OTHER_XML = b"""<export><rules>
  <rule name="R1" kind="pricing"><title>Discount rule</title><code>result = db.run("SELECT rate FROM Discounts d JOIN Tiers t ON d.t=t.id WHERE k=1")</code></rule>
  <rule><title>No ids here</title><note attr="SELECT a FROM  Hidden_Table  WHERE x=1">n</note></rule>
  <rule><title>Not SQL</title><code>print("selecting from the menu")</code></rule>
</rules></export>"""


def test_any_tag_names_any_call_syntax_and_attribute_text():
    idx = BmlIndex.from_xml_bytes(OTHER_XML)
    assert idx.tables == ["discounts", "hidden_table", "tiers"]
    m = idx.lookup("Discounts").matches[0]
    assert (m.node_tag, m.prop, m.path[-2:]) == ("code", "text", ("rules", "rule"))
    assert m.identity == {"title": "Discount rule"} and m.label.startswith("code#")   # no id/guid/name -> tag#node
    hidden = idx.lookup("hidden_table").matches[0]
    assert (hidden.node_tag, hidden.prop) == ("note", "attr")      # found in an attribute, not element text
    assert idx.lookup("menu").matches == ()                           # prose containing 'select' is not a query


def test_existing_projection_can_be_indexed_without_reparsing():
    from aryx.cpq_ingestion.raw_graph.xml_projector import project_xml_to_raw_graph
    idx = BmlIndex.from_projection(project_xml_to_raw_graph(OTHER_XML))
    assert idx.tables == ["discounts", "hidden_table", "tiers"]
