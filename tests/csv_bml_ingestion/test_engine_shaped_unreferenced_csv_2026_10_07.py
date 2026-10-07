"""A CSV no script reads is still loaded when the CPQ engine reads that table shape.

Workspace 1267 (2026-10-07): `BaseModelToConfig.csv` was landed as raw rows, then skipped with CBI_BML_NOT_FOUND
(no script queries it), so the engine could not map "APX 3000" to its CPQ model and model resolution fell back to a
fixed product. The platform itself, not a script, reads that table. The loader now builds the table from the CSV's
own header and types when the columns match a shape the engine reads; every other unreferenced CSV is skipped as before.
"""
from __future__ import annotations

import pytest

from aryx.csv_bml_ingestion import ingest_csv
from aryx.csv_bml_ingestion.csv_reader import to_column_name
from aryx.csv_bml_ingestion.engine_shapes import (
    LOAD_ENGINE_TABLES_ENV, engine_shape_of_columns, load_engine_tables_enabled,
)

from .conftest import FakeDb, write_csv

# the real BaseModelToConfig.csv header (9,725 rows on the SVX / Astro workspaces)
BASE_MODEL_HEADER = ["_update_action", "baseModel", "productFamily", "productLine", "cpqModel", "displayFamily",
                     "displayLine", "displayModel", "startDate", "endDate", "baseProductSelection",
                     "CPQModelVariableName", "attr1", "val1", "StandardBOM", "otherPOFlags", "pvPartNumber",
                     "apcRollupItem"]


def _base_model_csv(tmp_path, name="BaseModelToConfig.csv"):
    rows = [
        ["modify", "H1903A", "aSTRO25", "aSTRODevices", "APX3000", "ASTRO25", "ASTRO Devices", "APX 3000",
         "", "", "", "aPX3000", "", "", "", "", "", ""],
        ["modify", "T8523A", "aSTRO25", "aSTRODevices", "APX900", "ASTRO25", "ASTRO Devices", "APX 900",
         "", "", "", "aPX900", "", "", "", "", "", ""],
    ]
    return write_csv(tmp_path / name, BASE_MODEL_HEADER, ["String"] * len(BASE_MODEL_HEADER), rows)


def _columns(header):
    return tuple(to_column_name(h) for h in header)


# --- the shape test ----------------------------------------------------------------------------------------
def test_the_real_base_model_header_is_an_engine_shape():
    """Its attr1/val1 columns make the header 'constraint'-shaped as a whole; the engine reader classifies per row
    (empty cells are omitted), where the rows satisfy the base-model shape (see the reader test below)."""
    assert engine_shape_of_columns(_columns(BASE_MODEL_HEADER)) in {"constraint", "basemodel_to_config"}
    assert engine_shape_of_columns(_columns(BASE_MODEL_HEADER[:1] + BASE_MODEL_HEADER[1:11])) == "basemodel_to_config"


def test_a_header_the_engine_never_reads_is_not_a_shape():
    assert engine_shape_of_columns(("countrycode",)) is None
    assert engine_shape_of_columns(_columns(["name", "price_list_name", "fob_point"])) is None


def test_the_existing_data_table_shapes_are_still_recognised():
    seq = _columns(["_update_action", "key", "CPQModel", "BaseModel", "attr1", "val1", "AttrName", "Seq",
                    "optionOrReqFlag"])
    assert engine_shape_of_columns(seq) == "sequence"


# --- the pipeline ------------------------------------------------------------------------------------------
def test_an_unreferenced_engine_shaped_csv_is_loaded_with_a_schema_derived_from_its_header(bml_index, tmp_path):
    db = FakeDb()
    r = ingest_csv(_base_model_csv(tmp_path), bml_index, db)
    assert (r.status, r.table, r.rows_loaded, r.error_code) == ("loaded", "basemodeltoconfig", 2, "")
    assert r.bml_scripts == []                                   # no script reads it
    ddl = [e[1] for e in db.statements("execute")]
    create = next(s for s in ddl if s.startswith("CREATE TABLE IF NOT EXISTS basemodeltoconfig"))
    for column in ("basemodel VARCHAR2(", "cpqmodel VARCHAR2(", "displaymodel VARCHAR2(", "update_action VARCHAR2("):
        assert column in create
    assert not any(s.startswith("CREATE INDEX") for s in ddl)    # no access path is known, the engine reads it whole
    ins = db.statements("executemany")[0]
    assert ins[1].startswith("INSERT INTO basemodeltoconfig (update_action, basemodel") and len(ins[2]) == 2


def test_sizes_leave_headroom_over_the_longest_value(bml_index, tmp_path):
    long_name = "X" * 100
    p = write_csv(tmp_path / "BaseModelToConfig.csv", BASE_MODEL_HEADER, ["String"] * len(BASE_MODEL_HEADER),
                  [["modify", "B1", "f", "l", "M1", "f", "l", long_name, "", "", "", "v", "", "", "", "", "", ""]])
    db = FakeDb()
    assert ingest_csv(p, bml_index, db).status == "loaded"
    create = next(e[1] for e in db.statements("execute") if e[1].startswith("CREATE TABLE"))
    assert "displaymodel VARCHAR2(200)" in create               # twice the longest value
    assert "startdate VARCHAR2(64)" in create                   # floor of 64


def test_the_table_is_stamped_with_the_owner_tag_so_the_engine_reader_finds_it(bml_index, tmp_path):
    db = FakeDb()
    ingest_csv(_base_model_csv(tmp_path), bml_index, db)
    assert db.comments.get("BASEMODELTOCONFIG") == "csv_bml_ingestion"


def test_an_unreferenced_csv_the_engine_does_not_read_is_still_skipped(bml_index, tmp_path):
    p = write_csv(tmp_path / "ar1Matrix.csv", ["countryCode"], ["String"], [["US"]])
    db = FakeDb()
    r = ingest_csv(p, bml_index, db)
    assert (r.status, r.error_code) == ("skipped", "CBI_BML_NOT_FOUND")
    assert db.log == []


def test_the_opt_out_restores_the_old_skip(bml_index, tmp_path, monkeypatch):
    monkeypatch.setenv(LOAD_ENGINE_TABLES_ENV, "false")
    assert load_engine_tables_enabled() is False
    db = FakeDb()
    r = ingest_csv(_base_model_csv(tmp_path), bml_index, db)
    assert (r.status, r.error_code, r.table) == ("skipped", "CBI_BML_NOT_FOUND", "basemodeltoconfig")
    assert db.log == []


def test_the_switch_is_on_by_default(monkeypatch):
    monkeypatch.delenv(LOAD_ENGINE_TABLES_ENV, raising=False)
    assert load_engine_tables_enabled() is True


def test_a_script_referenced_table_still_uses_its_own_authored_schema(bml_index, tmp_path):
    """attrSequence is read by a script AND is an engine shape: the script-derived (pre-authored) schema wins."""
    seq_header = ["_update_action", "key", "CPQModel", "BaseModel", "attr1", "val1", "AttrName", "Seq",
                  "optionOrReqFlag", "startDate", "endDate", "createdDate", "createdBy", "updatedDate", "updatedBy"]
    p = write_csv(tmp_path / "attrSequence.csv", seq_header, ["String"] * 15,
                  [["modify", "k1", "M1", "B1", "", "", "attrA", "1", "R", "", "", "", "", "", ""]])
    db = FakeDb()
    r = ingest_csv(p, bml_index, db)
    assert r.status == "loaded" and r.bml_scripts == ["id=111"]
    assert any(e[1].startswith("CREATE INDEX") for e in db.statements("execute"))   # the authored indexes exist


# --- the engine reader --------------------------------------------------------------------------------------
def test_the_workspace_table_reader_restores_the_spelling_the_base_model_shape_needs():
    from aryx.cpq.data_table.data_table_inference import _is_basemodel_to_config_shaped
    from aryx.cpq.rdb import rdb_workspace_tables as wt

    columns = _columns(BASE_MODEL_HEADER)
    assert any(_is_basemodel_to_config_shaped({wt.recase(c, v) for c in columns}) for v in (0, 1))
    # the spelling the shape needs is one of the two variants the reader tries
    assert {"displayModel", "cpqModel", "baseModel"} <= {wt.recase(c, 1) for c in columns}


# --- review follow-ups: no silent failure, row-cap warning -----------------------------------------------------
def test_an_unexpected_failure_of_the_shape_check_is_logged_and_falls_back_to_skip(bml_index, tmp_path, monkeypatch, caplog):
    import logging

    from aryx.csv_bml_ingestion import pipeline

    def boom(columns):
        raise ImportError("engine package unavailable")

    monkeypatch.setattr(pipeline, "engine_shape_of_columns", boom)
    db = FakeDb()
    with caplog.at_level(logging.WARNING, logger=pipeline.__name__):
        r = ingest_csv(_base_model_csv(tmp_path), bml_index, db)
    assert (r.status, r.error_code) == ("skipped", "CBI_BML_NOT_FOUND")
    assert any("engine table shape check failed" in rec.getMessage() for rec in caplog.records)


def test_a_table_over_the_engines_row_cap_is_warned_about(bml_index, tmp_path, monkeypatch):
    monkeypatch.setenv("ARYX_CPQ_WS_TABLE_MAX_ROWS", "1")
    warnings = []
    from aryx.csv_bml_ingestion import pipeline
    monkeypatch.setattr(pipeline.RunTracker, "warn", lambda self, step, msg, **kw: warnings.append((msg, kw)))
    db = FakeDb()
    assert ingest_csv(_base_model_csv(tmp_path), bml_index, db).rows_loaded == 2
    assert any("more than the engine reads" in m and kw["rows_loaded"] == 2 and kw["read_cap"] == 1 for m, kw in warnings)
