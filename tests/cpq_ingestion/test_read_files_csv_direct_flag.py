"""read_files() flags a plain CSV upload's plan with cpq_csv_direct when
ARYX_INGEST_FILE_TYPE includes "csv" and the pipeline is active -- the
read-time half of the CSV direct-to-Postgres feature (see csv_land.py and
ingest_confirmed()'s dispatch for the confirm-time half).
"""
from __future__ import annotations

import pytest

from aryx.broker import Broker
from aryx.cpq_ingestion.config import get_cpq_ingestion_settings
from aryx.pipeline.doc_discovery.doc_discovery import read_files

SAMPLE_CSV = b"id,name\n1,Widget\n2,Gadget\n"


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_cpq_ingestion_settings.cache_clear()
    yield
    get_cpq_ingestion_settings.cache_clear()


def _read(monkeypatch, **env):
    for var in ("ARYX_INGEST_FILE_TYPE", "ARYX_INGEST_PIPELINE"):
        monkeypatch.delenv(var, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    get_cpq_ingestion_settings.cache_clear()
    return read_files(
        doc_paths=[], tabular=[(SAMPLE_CSV, "catalog.csv")],
        broker=Broker.__new__(Broker), context="", did="csv-flag-test",
    )


def test_flags_csv_plan_when_file_type_is_csv(monkeypatch):
    result = _read(monkeypatch, ARYX_INGEST_FILE_TYPE="csv", ARYX_INGEST_PIPELINE="cpq_ingestion")

    [plan] = result["tabular"]
    assert plan.get("cpq_csv_direct") is True


def test_does_not_flag_when_pipeline_inactive(monkeypatch):
    result = _read(monkeypatch)

    [plan] = result["tabular"]
    assert "cpq_csv_direct" not in plan


def test_does_not_flag_when_file_type_is_xml_only(monkeypatch):
    result = _read(monkeypatch, ARYX_INGEST_FILE_TYPE="xml", ARYX_INGEST_PIPELINE="cpq_ingestion")

    [plan] = result["tabular"]
    assert "cpq_csv_direct" not in plan


def test_flags_csv_plan_when_file_type_is_combined_xml_csv(monkeypatch):
    result = _read(monkeypatch, ARYX_INGEST_FILE_TYPE="xml,csv", ARYX_INGEST_PIPELINE="cpq_ingestion")

    [plan] = result["tabular"]
    assert plan.get("cpq_csv_direct") is True


def test_flagged_csv_plan_has_no_source_filename_or_source_bytes(monkeypatch):
    """A plain CSV upload is its own file, not a fan-out from a parent
    workbook -- it must not pick up the source_filename/source_bytes
    fields _persist_tabular_sources() uses for XML/XLSX cataloging."""
    result = _read(monkeypatch, ARYX_INGEST_FILE_TYPE="csv", ARYX_INGEST_PIPELINE="cpq_ingestion")

    [plan] = result["tabular"]
    assert "source_filename" not in plan
    assert "source_bytes" not in plan


def test_flagged_plan_still_carries_the_csv_data_for_landing(monkeypatch):
    result = _read(monkeypatch, ARYX_INGEST_FILE_TYPE="csv", ARYX_INGEST_PIPELINE="cpq_ingestion")

    [plan] = result["tabular"]
    assert plan["filename"] == "catalog.csv"
    assert plan["data"]
