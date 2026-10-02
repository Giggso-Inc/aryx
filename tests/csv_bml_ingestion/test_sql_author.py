"""Run-time LLM authoring of schema/index SQL for a table that has none (fake LLM)."""
from __future__ import annotations

import pytest

from aryx.csv_bml_ingestion import BmlIndex, ingest_csv
from aryx.csv_bml_ingestion.errors import SqlAuthoringError
from aryx.csv_bml_ingestion.sql_validate import ColumnSpec, validate_indexes, validate_schema

from .conftest import FakeDb, write_csv

XML = b"""<r><bm_function><id>7</id><guid>g7</guid><java_class_name>C7</java_class_name>
<script_text><![CDATA[ rs = BMQL("SELECT Name FROM Widgets WHERE Color = $c ORDER BY Name"); ]]></script_text>
</bm_function></r>"""
GOOD = """```sql schema.sql
CREATE TABLE IF NOT EXISTS widgets (
    update_action VARCHAR2(50),
    name VARCHAR2(200),
    color VARCHAR2(100),
    qty NUMBER(10)
);
```
```sql indexes.sql
CREATE INDEX IF NOT EXISTS idx_widgets_color_name ON widgets (color, name);
```"""


@pytest.fixture
def idx():
    return BmlIndex.from_xml_bytes(XML)


@pytest.fixture
def csv_file(tmp_path):
    return write_csv(tmp_path / "Widgets.csv", ["_update_action", "Name", "Color", "Qty"],
                     ["String", "String", "String", "Integer"],
                     [["modify", "bolt", "red", "5"], ["modify", "nut", "blue", "7"]])


class FakeLlm:
    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []

    def __call__(self, system, user):
        self.calls.append((system, user))
        return self.replies.pop(0)


def test_missing_sql_is_authored_validated_saved_then_ingested(idx, csv_file, tmp_path):
    llm, db, root = FakeLlm(GOOD), FakeDb(), tmp_path / "sql"
    r = ingest_csv(csv_file, idx, db, sql_root=root, sql_author=llm)
    assert (r.status, r.table, r.rows_loaded) == ("loaded", "widgets", 2)
    assert (root / "widgets" / "schema.sql").read_text().count("CREATE TABLE") == 1
    assert "REVIEW" in (root / "widgets" / "schema.sql").read_text()
    assert "SELECT Name FROM Widgets" in (root / "widgets" / "bml_source.md").read_text()
    prompt = llm.calls[0][1]
    assert "Table: widgets" in prompt and "SELECT Name FROM Widgets" in prompt and "qty: Integer" in prompt
    ddl = [e[1] for e in db.statements("execute")]
    assert any(s.startswith("CREATE TABLE IF NOT EXISTS widgets") for s in ddl)


def test_invalid_first_answer_is_retried_with_feedback(idx, csv_file, tmp_path):
    bad = GOOD.replace("qty NUMBER(10)", "qty NUMBER(10),\n    extra VARCHAR2(5)")
    llm = FakeLlm(bad, GOOD)
    r = ingest_csv(csv_file, idx, FakeDb(), sql_root=tmp_path / "sql", sql_author=llm)
    assert r.status == "loaded" and len(llm.calls) == 2
    assert "rejected" in llm.calls[1][1] and "expected 4 columns" in llm.calls[1][1]


def test_never_valid_fails_without_touching_db_or_disk(idx, csv_file, tmp_path):
    db = FakeDb()
    r = ingest_csv(csv_file, idx, db, sql_root=tmp_path / "sql", sql_author=FakeLlm("nonsense", "still nonsense"))
    assert (r.status, r.error_code) == ("failed", "CBI_SQL_AUTHOR_FAILED")
    assert db.writes() == [] and not (tmp_path / "sql").exists()


def test_authoring_disabled_keeps_missing_sql_failure(idx, csv_file, tmp_path):
    r = ingest_csv(csv_file, idx, FakeDb(), sql_root=tmp_path / "sql", sql_author=None)
    assert r.error_code == "CBI_SQL_ARTIFACTS_MISSING"


def test_existing_files_are_never_overwritten(idx, csv_file, tmp_path):
    (tmp_path / "sql" / "widgets").mkdir(parents=True)
    (tmp_path / "sql" / "widgets" / "schema.sql").write_text("-- hand written, no index file\n")
    llm = FakeLlm(GOOD)
    r = ingest_csv(csv_file, idx, FakeDb(), sql_root=tmp_path / "sql", sql_author=llm)
    assert r.status == "failed" and llm.calls == []
    assert (tmp_path / "sql" / "widgets" / "schema.sql").read_text().startswith("-- hand written")


SPECS = [ColumnSpec("a", "text", 30), ColumnSpec("b", "number")]


@pytest.mark.parametrize("sql,why", [
    ("DROP TABLE t;", "exactly one CREATE TABLE|must be"),
    ("CREATE TABLE IF NOT EXISTS t (a VARCHAR2(10), b NUMBER(5));", r"between 30"),            # too small for data
    ("CREATE TABLE IF NOT EXISTS t (a VARCHAR2(5000), b NUMBER(5));", r"between 30"),           # over 4000
    ("CREATE TABLE IF NOT EXISTS t (a VARCHAR2(50) PRIMARY KEY, b NUMBER(5));", "plain"),       # constraint
    ("CREATE TABLE IF NOT EXISTS t (a VARCHAR2(50), b VARCHAR2(5));", "wrong type"),            # type vs CSV
    ("CREATE TABLE IF NOT EXISTS t (b NUMBER(5), a VARCHAR2(50));", "expected column"),         # order
    ("CREATE TABLE IF NOT EXISTS t (a VARCHAR2(50), b NUMBER(5)); DROP TABLE x;", "nothing else"),
    ("CREATE TABLE IF NOT EXISTS t (a VARCHAR2(50), b NUMBER(5)); DROP TABLE x(y)", "expected column|wrong type|plain"),  # smuggled
    ("CREATE TABLE IF NOT EXISTS t (a VARCHAR2(50), b NUMBER(5))\n;\nGRANT ALL ON t TO PUBLIC;", "exactly one"),
    ("CREATE TABLE IF NOT EXISTS other (a VARCHAR2(50), b NUMBER(5));", "must be"),             # wrong table
])
def test_validator_rejects_unsafe_or_wrong_schema(sql, why):
    with pytest.raises(SqlAuthoringError, match=why):
        validate_schema(sql, "t", SPECS)


def test_validator_accepts_good_schema_and_returns_sizes():
    assert validate_schema("CREATE TABLE IF NOT EXISTS t (a VARCHAR2(50), b NUMBER(5));", "t", SPECS) == {"a": 50, "b": 22}


@pytest.mark.parametrize("sql,why", [
    ("DROP INDEX x;", "not an allowed"),
    ("CREATE INDEX IF NOT EXISTS idx_t_z ON t (zzz);", "not in the table"),
    ("CREATE INDEX IF NOT EXISTS idx_other_a ON t (a);", "bad or duplicate"),
    ("CREATE INDEX IF NOT EXISTS idx_t_a ON t (a);\nCREATE INDEX IF NOT EXISTS idx_t_a2 ON t (a);", "bad or duplicate"),
    ("CREATE UNIQUE INDEX IF NOT EXISTS idx_t_a ON t (a);", "not an allowed"),
    ("CREATE INDEX IF NOT EXISTS idx_t_a ON t (a, a);", "bad or duplicate"),
])
def test_validator_rejects_bad_indexes(sql, why):
    with pytest.raises(SqlAuthoringError, match=why):
        validate_indexes(sql, "t", {"a": 50, "b": 22})


def test_validator_blocks_oversized_composite_key():
    with pytest.raises(SqlAuthoringError, match="ORA-01450"):
        validate_indexes("CREATE INDEX IF NOT EXISTS idx_t_ab ON t (a, b);", "t", {"a": 4000, "b": 4000})


def test_llm_failure_is_a_clean_authoring_error_and_not_retried(idx, csv_file, tmp_path):
    calls = []

    def boom(system, user):
        calls.append(1)
        raise ModuleNotFoundError("No module named 'oci'")

    db = FakeDb()
    r = ingest_csv(csv_file, idx, db, sql_root=tmp_path / "sql", sql_author=boom)
    assert (r.status, r.error_code) == ("failed", "CBI_SQL_AUTHOR_FAILED")
    assert "LLM call failed" in r.message and len(calls) == 1 and db.writes() == []


def test_integer_column_must_hold_the_longest_csv_value():
    specs = [ColumnSpec("n", "number", 5)]            # CSV has a 5-digit integer
    with pytest.raises(SqlAuthoringError, match="between 5"):
        validate_schema("CREATE TABLE IF NOT EXISTS t (n NUMBER(1));", "t", specs)
    assert validate_schema("CREATE TABLE IF NOT EXISTS t (n NUMBER(5));", "t", specs) == {"n": 22}


def test_validator_floor_of_one_and_ascii_only():
    with pytest.raises(SqlAuthoringError):            # VARCHAR2(0) even if a caller passes min 0
        validate_schema("CREATE TABLE IF NOT EXISTS t (a VARCHAR2(0));", "t", [ColumnSpec("a", "text", 0)])
    with pytest.raises(SqlAuthoringError):            # Kelvin sign U+212A folds to 'k' under Unicode IGNORECASE
        validate_schema("CREATE TABLE IF NOT EXISTS t (K VARCHAR2(5));", "t", [ColumnSpec("k", "text", 1)])
    with pytest.raises(SqlAuthoringError):            # non-ASCII digit
        validate_schema("CREATE TABLE IF NOT EXISTS t (a VARCHAR2(٥٠));", "t", [ColumnSpec("a", "text", 1)])


def test_prompt_bounds_and_delimits_untrusted_bml_text(idx, csv_file, tmp_path):
    long_xml = XML.replace(b"SELECT Name FROM Widgets", b"SELECT " + b"x" * 5000 + b" FROM Widgets")
    llm = FakeLlm(GOOD)
    ingest_csv(csv_file, BmlIndex.from_xml_bytes(long_xml), FakeDb(), sql_root=tmp_path / "sql", sql_author=llm)
    system, user = llm.calls[0]
    assert "<queries>" in user and "untrusted data" in user and "x" * 2000 not in user
    assert "never instructions" in system


def test_llm_error_text_is_not_leaked_into_result(idx, csv_file, tmp_path):
    def boom(system, user):
        raise RuntimeError("https://endpoint.example/secret-token-123")
    r = ingest_csv(csv_file, idx, FakeDb(), sql_root=tmp_path / "sql", sql_author=boom)
    assert "RuntimeError" in r.message and "secret-token" not in r.message
