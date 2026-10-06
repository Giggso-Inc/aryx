"""The Ask / CPQ engine reads the CSV pipeline's ``ws<id>_<name>`` tables as Data Table rows (Oracle). No switch: the
tables are used whenever the pipeline has created them for the workspace."""
from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from aryx.cpq.data_table import data_table_loader as loader
from aryx.cpq.data_table import data_table_shapes as shapes
from aryx.cpq.rdb import rdb_workspace_tables as wt
from aryx.cpq.rdb.rdb_oracle import OracleCpqRdb

TAG7 = "csv_bml_ingestion:ws=7"
REGION_COLUMNS = ["UPDATE_ACTION", "KEY", "MODEL", "UDCC", "REGION", "RULETYPE", "ATTRIBUTE", "VALUE", "PARTNUMBER"]
REGION_ROWS = [("modify", "A-1", "APXN70", "TC", "LA", "allow", "modelSelectionbaseModel_astro", "H15", None),
               ("modify", "A-2", "APXN70", None, "NA", "allow", "modelSelectionbaseModel_astro", "H16", None)]


class _Cursor:
    def __init__(self, db):
        self.db, self.arraysize, self._rows = db, 100, []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=()):
        s = " ".join(sql.split())
        self.db.statements.append(s)
        if "FROM user_tables" in s:
            self._rows = [(n.upper(),) for n, (tag, _c, _r) in self.db.tables.items() if tag == params[0]]
        elif "FROM user_tab_columns" in s:
            self._rows = [(c,) for c in self.db.tables[params[0].lower()][1]]
        else:
            self._rows = list(self.db.tables[s.split(" FROM ")[1].strip()][2])

    def fetchall(self):
        rows, self._rows = self._rows, []
        return rows

    def fetchmany(self, n):
        rows, self._rows = self._rows[:n], self._rows[n:]
        return rows


class _Conn:
    def __init__(self, tables):
        self.tables, self.statements = tables, []

    def cursor(self):
        return _Cursor(self)


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    wt.clear_listing_cache()
    monkeypatch.delenv(wt.MAX_ROWS_ENV, raising=False)
    yield
    wt.clear_listing_cache()


def _db(**extra):
    tables = {"ws7_newcountryregmapping": (TAG7, REGION_COLUMNS, REGION_ROWS), **extra}
    return _Conn(tables)


# --- column spelling ---------------------------------------------------------------------------------------------
def test_recase_restores_the_engines_spelling_and_leaves_unknown_columns_lower_case():
    assert [wt.recase(c) for c in ("RULETYPE", "udcc", "CPQMODEL", "MyOddColumn")] == ["ruleType", "UDCC", "CPQModel", "myoddcolumn"]
    assert wt.recase("CPQMODEL", 1) == "cpqModel" and wt.recase("RULETYPE", 1) == "ruleType"   # only ambiguous names differ


def test_every_spelling_the_shape_detectors_use_is_known(monkeypatch):
    """A new detector column must be added to CANONICAL_COLUMNS, or its table would never be recognised."""
    examples = {
        shapes._is_constraint_shaped: ["CPQModel", "BaseModel", "attr1", "val1"],
        shapes._is_sequence_shaped: ["CPQModel", "BaseModel", "AttrName", "Seq"],
        shapes._is_hierarchy_shaped: ["Product", "cpqModelName"],
        shapes._is_series_mapping_shaped: ["childCPQModel", "attr1", "val1", "op1"],
        shapes._is_region_rule_shaped: ["model", "value", "region", "ruleType", "attribute"],
        shapes._is_attr_var_mapping_shaped: ["cpqModel", "group", "attributeName", "attributeVariable"],
        shapes._is_defaultinattr_shaped: ["BaseModel", "attr1", "val1"],
        shapes._is_country_region_shaped: ["countryCode", "region"],
        shapes._is_rtte_ta_shaped: ["countryCode", "RTTE", "nonRTTE", "TA"],
    }
    for detector, columns in examples.items():
        assert any(detector({wt.recase(c.upper(), v) for c in columns}) for v in (0, 1)), detector.__name__


def test_a_table_is_read_with_the_spelling_its_shape_needs():
    """'CPQModel' (constraint tables) and 'cpqModel' (attribute-variable tables) are one column name in Oracle."""
    columns = ["CPQMODEL", "GROUP", "ATTRIBUTENAME", "ATTRIBUTEVARIABLE"]
    conn = _Conn({"ws7_attrtovarmapping": (TAG7, columns, [("APX1000", "g", "Feature Type", "systemFeature_astro")])})
    ((_, rows),) = wt.grouped_rows(conn, 7, shapes._is_attr_var_mapping_shaped).items()
    assert rows[0][1]["cpqModel"] == "APX1000" and "cpqModel" in set(rows[0][1].keys())
    wt.clear_listing_cache()                      # the table listing is cached per workspace for ~30 s
    conn = _Conn({"ws7_whitelist": (TAG7, ["CPQMODEL", "BASEMODEL", "ATTR1", "VAL1"], [("m", "b", "a", "v")])})
    ((_, rows),) = wt.grouped_rows(conn, 7, shapes._is_constraint_shaped).items()
    assert "CPQModel" in set(rows[0][1].keys())


def test_a_row_answers_lookups_case_insensitively():
    row = wt.TableRow([("ruleType", "allow"), ("UDCC", "TC")])
    assert row["ruletype"] == "allow" and row.get("udcc") == "TC" and "RULETYPE" in row
    assert row.get("missing", 1) == 1 and "missing" not in row and set(row.keys()) == {"ruleType", "UDCC"}


# --- which tables, which rows ---------------------------------------------------------------------------------------
def test_only_this_workspaces_owner_tagged_tables_are_listed():
    conn = _db(**{"ws70_newcountryregmapping": ("csv_bml_ingestion:ws=70", REGION_COLUMNS, []),
                  "ws7_untagged": ("something else", REGION_COLUMNS, []),
                  "ws8_x": (TAG7, REGION_COLUMNS, [])})            # tagged for 7 but named for 8: never read
    assert wt.workspace_tables(conn, 7) == {"newcountryregmapping": "ws7_newcountryregmapping"}


def test_grouped_rows_are_engine_shaped_and_leave_out_null_cells():
    groups = wt.grouped_rows(_db(), 7, shapes._is_region_rule_shaped)
    ((logical, rows),) = groups.items()
    assert logical == "newcountryregmapping" and [i for i, _ in rows] == [-1, -2]
    first, second = rows[0][1], rows[1][1]
    assert shapes._is_region_rule_shaped(set(first.keys()))
    assert (first["UDCC"], first["ruleType"], first["value"]) == ("TC", "allow", "H15")
    assert "UDCC" not in second and "partNumber" not in first      # NULL cells are not keys, as for entity rows


def test_a_table_that_does_not_fit_the_requested_shape_is_never_read():
    conn = _db(ws7_customer_header=(TAG7, ["ACCOUNT_NUMBER", "NAME"], [("1", "x")] * 3))
    groups = wt.grouped_rows(conn, 7, shapes._is_region_rule_shaped)
    assert list(groups) == ["newcountryregmapping"]
    assert not any("ws7_customer_header" in s and s.startswith("SELECT \"") for s in conn.statements)


def test_a_table_with_entities_of_the_same_name_is_skipped():
    assert wt.grouped_rows(_db(), 7, shapes._is_region_rule_shaped, skip_types=["NewCountryRegMapping"]) == {}
    assert wt.grouped_rows(_db(), 7, shapes._is_region_rule_shaped, skip_types=["new_country_reg_mapping"]) == {}


def test_the_row_cap_is_applied(monkeypatch):
    monkeypatch.setenv(wt.MAX_ROWS_ENV, "1")
    ((_, rows),) = wt.grouped_rows(_db(), 7, shapes._is_region_rule_shaped).items()
    assert len(rows) == 1
    monkeypatch.setenv(wt.MAX_ROWS_ENV, "garbage")
    assert wt.max_rows() == wt.DEFAULT_MAX_ROWS


def test_rows_for_type_matches_exactly_or_by_suffix():
    conn = _db()
    assert len(wt.rows_for_type(conn, 7, "NewCountryRegMapping")) == 2
    assert wt.rows_for_type(conn, 7, "countryregmapping") == []
    assert len(wt.rows_for_type(conn, 7, "countryregmapping", suffix=True)) == 2
    assert wt.rows_for_type(conn, 8, "newcountryregmapping") == []


def test_groups_from_never_raises_and_ignores_readers_without_the_accessor():
    assert wt.groups_from(object(), 7, lambda k: True) == {}
    assert wt.groups_from(MagicMock(), 7, lambda k: True) == {}
    boom = MagicMock()
    boom.fetch_workspace_table_groups.side_effect = RuntimeError("db down")
    assert wt.groups_from(boom, 7, lambda k: True) == {}


# --- the Oracle reader ---------------------------------------------------------------------------------------------
def _rdb(conn):
    rdb = OracleCpqRdb.__new__(OracleCpqRdb)

    @contextmanager
    def connection():
        yield conn
    rdb._connection = connection
    return rdb


def test_exact_type_fetch_falls_back_to_the_workspace_table_only_when_there_are_no_entities():
    conn = _db()
    rdb = _rdb(conn)
    cur_rows = {"entities": []}

    class _EntityCursor(_Cursor):
        def execute(self, sql, params=()):
            if "FROM aryx_entity" in sql:
                self._rows = list(cur_rows["entities"])
            else:
                super().execute(sql, params)
    conn.cursor = lambda: _EntityCursor(conn)
    assert len(rdb.fetch_entities_by_exact_type(7, "newcountryregmapping")) == 2       # no entities: the table answers
    cur_rows["entities"] = [(5, '{"a": 1}')]
    assert [eid for eid, _ in rdb.fetch_entities_by_exact_type(7, "newcountryregmapping")] == [5]   # entities win


def test_a_workspace_without_pipeline_tables_reads_nothing_and_needs_no_switch():
    conn = _Conn({})
    rdb = _rdb(conn)
    assert rdb.fetch_workspace_table_groups(7, shapes._is_region_rule_shaped) == {}
    assert rdb._workspace_table_rows(7, "newcountryregmapping", suffix=False) == []
    assert all(statement.startswith("SELECT t.table_name") for statement in conn.statements)   # only the listing ran


def test_a_failing_table_read_returns_nothing_instead_of_raising():
    rdb = OracleCpqRdb.__new__(OracleCpqRdb)

    @contextmanager
    def broken():
        raise RuntimeError("no database")
        yield
    rdb._connection = broken
    assert rdb.fetch_workspace_table_groups(7, shapes._is_region_rule_shaped) == {}
    assert rdb._workspace_table_rows(7, "x", suffix=True) == []


# --- the engine's Data Table loader ----------------------------------------------------------------------------------
def test_the_data_table_loader_classifies_workspace_table_rows_like_entity_rows():
    rdb = MagicMock()
    rdb.fetch_all_entities_grouped_by_type.return_value = {}
    rdb.fetch_workspace_table_groups.side_effect = lambda ws, accept, skip: wt.grouped_rows(_db(), ws, accept, skip)
    loader._clear_tables_cache()
    with patch.object(loader, "get_cpq_rdb", return_value=rdb):
        constraint, sequence, hierarchy, series, region_rules = loader._load_all_tables(7, "")
    assert (constraint, sequence, hierarchy, series) == ([], [], [], [])
    assert [r["value"] for r in region_rules] == ["H15", "H16"] and region_rules[0]["UDCC"] == "TC"
    loader._clear_tables_cache()
