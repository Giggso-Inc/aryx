"""cpq_ingestion_pipeline_active / cpq_layout_upload_active — env-var
activation matrices. partition_cpq_ingestion_plans — grouping tabular
plans by source XML file for the resolve/relate bridge."""
from __future__ import annotations

import pytest

from aryx.cpq_ingestion.config import get_cpq_ingestion_settings
from aryx.cpq_ingestion.routing import (
    cpq_ingestion_pipeline_active,
    cpq_layout_upload_active,
    partition_cpq_ingestion_csv_plans,
    partition_cpq_ingestion_plans,
)


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_cpq_ingestion_settings.cache_clear()
    yield
    get_cpq_ingestion_settings.cache_clear()


def test_inactive_when_neither_env_var_set(monkeypatch):
    monkeypatch.delenv("ARYX_INGEST_FILE_TYPE", raising=False)
    monkeypatch.delenv("ARYX_INGEST_PIPELINE", raising=False)
    assert cpq_ingestion_pipeline_active("catalog.xml") is False


def test_inactive_when_only_file_type_set(monkeypatch):
    monkeypatch.setenv("ARYX_INGEST_FILE_TYPE", "xml")
    monkeypatch.delenv("ARYX_INGEST_PIPELINE", raising=False)
    assert cpq_ingestion_pipeline_active("catalog.xml") is False


def test_inactive_when_only_pipeline_set(monkeypatch):
    monkeypatch.delenv("ARYX_INGEST_FILE_TYPE", raising=False)
    monkeypatch.setenv("ARYX_INGEST_PIPELINE", "cpq_ingestion")
    assert cpq_ingestion_pipeline_active("catalog.xml") is False


def test_active_for_matching_xml_upload(monkeypatch):
    monkeypatch.setenv("ARYX_INGEST_FILE_TYPE", "xml")
    monkeypatch.setenv("ARYX_INGEST_PIPELINE", "cpq_ingestion")
    assert cpq_ingestion_pipeline_active("aSTRO25_ConfigData.xml") is True


# ── ARYX_INGEST_FILE_TYPE as a comma-separated list (xml + csv together) ────

def test_active_for_csv_when_file_type_is_csv(monkeypatch):
    monkeypatch.setenv("ARYX_INGEST_FILE_TYPE", "csv")
    monkeypatch.setenv("ARYX_INGEST_PIPELINE", "cpq_ingestion")
    assert cpq_ingestion_pipeline_active("catalog.csv") is True


def test_csv_only_file_type_does_not_activate_for_xml(monkeypatch):
    monkeypatch.setenv("ARYX_INGEST_FILE_TYPE", "csv")
    monkeypatch.setenv("ARYX_INGEST_PIPELINE", "cpq_ingestion")
    assert cpq_ingestion_pipeline_active("catalog.xml") is False


def test_combined_xml_csv_file_type_activates_both(monkeypatch):
    monkeypatch.setenv("ARYX_INGEST_FILE_TYPE", "xml,csv")
    monkeypatch.setenv("ARYX_INGEST_PIPELINE", "cpq_ingestion")
    assert cpq_ingestion_pipeline_active("catalog.xml") is True
    assert cpq_ingestion_pipeline_active("catalog.csv") is True


def test_combined_file_type_does_not_activate_unrelated_extensions(monkeypatch):
    monkeypatch.setenv("ARYX_INGEST_FILE_TYPE", "xml,csv")
    monkeypatch.setenv("ARYX_INGEST_PIPELINE", "cpq_ingestion")
    assert cpq_ingestion_pipeline_active("catalog.json") is False


def test_combined_file_type_tolerates_whitespace_and_case(monkeypatch):
    monkeypatch.setenv("ARYX_INGEST_FILE_TYPE", " XML , .CSV ")
    monkeypatch.setenv("ARYX_INGEST_PIPELINE", "cpq_ingestion")
    assert cpq_ingestion_pipeline_active("catalog.xml") is True
    assert cpq_ingestion_pipeline_active("catalog.csv") is True


def test_pipeline_name_is_case_insensitive(monkeypatch):
    monkeypatch.setenv("ARYX_INGEST_FILE_TYPE", "XML")
    monkeypatch.setenv("ARYX_INGEST_PIPELINE", "CPQ_Ingestion")
    assert cpq_ingestion_pipeline_active("catalog.xml") is True


def test_inactive_for_non_matching_file_type(monkeypatch):
    monkeypatch.setenv("ARYX_INGEST_FILE_TYPE", "csv")
    monkeypatch.setenv("ARYX_INGEST_PIPELINE", "cpq_ingestion")
    assert cpq_ingestion_pipeline_active("catalog.xml") is False


def test_inactive_for_unrelated_pipeline_value(monkeypatch):
    monkeypatch.setenv("ARYX_INGEST_FILE_TYPE", "xml")
    monkeypatch.setenv("ARYX_INGEST_PIPELINE", "some_other_pipeline")
    assert cpq_ingestion_pipeline_active("catalog.xml") is False


def test_leading_dot_in_configured_file_type_is_tolerated(monkeypatch):
    monkeypatch.setenv("ARYX_INGEST_FILE_TYPE", ".xml")
    monkeypatch.setenv("ARYX_INGEST_PIPELINE", "cpq_ingestion")
    assert cpq_ingestion_pipeline_active("catalog.xml") is True


# ── cpq_layout_upload_active ────────────────────────────────────────────────
# Requires BOTH ARYX_INGEST_PIPELINE=cpq_ingestion AND ARYX_CPQ_LAYOUT_SOURCE
# set -- deliberately NOT the same single-flag shape as
# cpq_ingestion_pipeline_active, so a deployment can run XML raw-graph
# writes without every .txt/.json upload silently being diverted away
# from normal ingestion.


def test_layout_inactive_when_neither_flag_set(monkeypatch):
    monkeypatch.delenv("ARYX_INGEST_PIPELINE", raising=False)
    monkeypatch.delenv("ARYX_CPQ_LAYOUT_SOURCE", raising=False)
    assert cpq_layout_upload_active("layout.txt") is False


def test_layout_inactive_when_only_pipeline_set(monkeypatch):
    """ARYX_INGEST_PIPELINE alone is NOT enough -- unlike the XML
    raw-graph path, this requires the second, explicit opt-in."""
    monkeypatch.setenv("ARYX_INGEST_PIPELINE", "cpq_ingestion")
    monkeypatch.delenv("ARYX_CPQ_LAYOUT_SOURCE", raising=False)
    assert cpq_layout_upload_active("layout.txt") is False


def test_layout_inactive_when_only_layout_source_set(monkeypatch):
    monkeypatch.delenv("ARYX_INGEST_PIPELINE", raising=False)
    monkeypatch.setenv("ARYX_CPQ_LAYOUT_SOURCE", "oracle")
    assert cpq_layout_upload_active("layout.txt") is False


def test_layout_active_for_txt_when_both_flags_set(monkeypatch):
    monkeypatch.setenv("ARYX_INGEST_PIPELINE", "cpq_ingestion")
    monkeypatch.setenv("ARYX_CPQ_LAYOUT_SOURCE", "oracle")
    assert cpq_layout_upload_active("Config Layout APX Next.txt") is True


def test_layout_active_for_json_when_both_flags_set(monkeypatch):
    monkeypatch.setenv("ARYX_INGEST_PIPELINE", "cpq_ingestion")
    monkeypatch.setenv("ARYX_CPQ_LAYOUT_SOURCE", "oracle")
    assert cpq_layout_upload_active("layout.json") is True


def test_layout_inactive_for_xml_even_with_both_flags_set(monkeypatch):
    """XML stays on the raw-graph path (cpq_ingestion_pipeline_active),
    never the layout-store path -- the two gates are independent."""
    monkeypatch.setenv("ARYX_INGEST_PIPELINE", "cpq_ingestion")
    monkeypatch.setenv("ARYX_CPQ_LAYOUT_SOURCE", "oracle")
    assert cpq_layout_upload_active("catalog.xml") is False


def test_layout_active_independent_of_ingest_file_type(monkeypatch):
    """cpq_layout_upload_active does NOT consult ARYX_INGEST_FILE_TYPE --
    it stays XML-specific for cpq_ingestion_pipeline_active, unrelated to
    which files route to the layout store."""
    monkeypatch.setenv("ARYX_INGEST_PIPELINE", "cpq_ingestion")
    monkeypatch.setenv("ARYX_CPQ_LAYOUT_SOURCE", "oracle")
    monkeypatch.setenv("ARYX_INGEST_FILE_TYPE", "xml")
    assert cpq_layout_upload_active("layout.txt") is True


def test_layout_inactive_for_unrelated_pipeline_value(monkeypatch):
    monkeypatch.setenv("ARYX_INGEST_PIPELINE", "some_other_pipeline")
    monkeypatch.setenv("ARYX_CPQ_LAYOUT_SOURCE", "oracle")
    assert cpq_layout_upload_active("layout.txt") is False


def test_layout_active_for_any_non_empty_layout_source_value(monkeypatch):
    """Any non-empty value activates -- the gate is "is this opted in at
    all", not a specific string match (unlike ingest_pipeline, which
    must equal the literal "cpq_ingestion")."""
    monkeypatch.setenv("ARYX_INGEST_PIPELINE", "cpq_ingestion")
    monkeypatch.setenv("ARYX_CPQ_LAYOUT_SOURCE", "anything-non-empty")
    assert cpq_layout_upload_active("layout.txt") is True


# ── partition_cpq_ingestion_plans ────────────────────────────────────────────

def _xml_plan(filename: str, source_filename: str) -> dict:
    return {"filename": filename, "source_filename": source_filename, "source_bytes": b"<x/>"}


def _csv_plan(filename: str) -> dict:
    return {"filename": filename}


def test_partition_groups_multiple_tag_plans_under_one_source_file(monkeypatch):
    monkeypatch.setenv("ARYX_INGEST_FILE_TYPE", "xml")
    monkeypatch.setenv("ARYX_INGEST_PIPELINE", "cpq_ingestion")
    plans = [
        _xml_plan("po_PurchaseOrder.csv", "po.xml"),
        _xml_plan("po_Customer.csv", "po.xml"),
    ]

    grouped, remaining = partition_cpq_ingestion_plans(plans)

    assert list(grouped.keys()) == ["po.xml"]
    assert remaining == []


def test_partition_keeps_the_first_plan_seen_per_source_file(monkeypatch):
    monkeypatch.setenv("ARYX_INGEST_FILE_TYPE", "xml")
    monkeypatch.setenv("ARYX_INGEST_PIPELINE", "cpq_ingestion")
    first = _xml_plan("po_PurchaseOrder.csv", "po.xml")
    second = _xml_plan("po_Customer.csv", "po.xml")

    grouped, _ = partition_cpq_ingestion_plans([first, second])

    assert grouped["po.xml"] is first


def test_partition_separates_two_distinct_source_files(monkeypatch):
    monkeypatch.setenv("ARYX_INGEST_FILE_TYPE", "xml")
    monkeypatch.setenv("ARYX_INGEST_PIPELINE", "cpq_ingestion")
    plans = [_xml_plan("a_Type1.csv", "a.xml"), _xml_plan("b_Type1.csv", "b.xml")]

    grouped, remaining = partition_cpq_ingestion_plans(plans)

    assert set(grouped.keys()) == {"a.xml", "b.xml"}
    assert remaining == []


def test_partition_leaves_inactive_xml_plans_in_remaining(monkeypatch):
    monkeypatch.delenv("ARYX_INGEST_FILE_TYPE", raising=False)
    monkeypatch.delenv("ARYX_INGEST_PIPELINE", raising=False)
    plans = [_xml_plan("po_PurchaseOrder.csv", "po.xml")]

    grouped, remaining = partition_cpq_ingestion_plans(plans)

    assert grouped == {}
    assert remaining == plans


def test_partition_leaves_plans_without_source_filename_in_remaining(monkeypatch):
    monkeypatch.setenv("ARYX_INGEST_FILE_TYPE", "xml")
    monkeypatch.setenv("ARYX_INGEST_PIPELINE", "cpq_ingestion")
    plans = [_csv_plan("regular.csv")]

    grouped, remaining = partition_cpq_ingestion_plans(plans)

    assert grouped == {}
    assert remaining == plans


def test_partition_leaves_non_xml_source_files_in_remaining(monkeypatch):
    monkeypatch.setenv("ARYX_INGEST_FILE_TYPE", "xml")
    monkeypatch.setenv("ARYX_INGEST_PIPELINE", "cpq_ingestion")
    plans = [{"filename": "sheet.csv", "source_filename": "workbook.xlsx", "source_bytes": b"x"}]

    grouped, remaining = partition_cpq_ingestion_plans(plans)

    assert grouped == {}
    assert remaining == plans


def test_partition_empty_input_returns_empty_outputs():
    assert partition_cpq_ingestion_plans([]) == ({}, [])


def test_partition_mixed_batch_separates_xml_and_regular_plans(monkeypatch):
    monkeypatch.setenv("ARYX_INGEST_FILE_TYPE", "xml")
    monkeypatch.setenv("ARYX_INGEST_PIPELINE", "cpq_ingestion")
    xml_plan = _xml_plan("po_PurchaseOrder.csv", "po.xml")
    csv_plan = _csv_plan("regular.csv")

    grouped, remaining = partition_cpq_ingestion_plans([xml_plan, csv_plan])

    assert list(grouped.values()) == [xml_plan]
    assert remaining == [csv_plan]


# ── partition_cpq_ingestion_csv_plans ────────────────────────────────────────

def test_csv_partition_splits_flagged_plans_out():
    flagged = {"filename": "catalog.csv", "cpq_csv_direct": True}
    unflagged = _csv_plan("regular.csv")

    csv_plans, remaining = partition_cpq_ingestion_csv_plans([flagged, unflagged])

    assert csv_plans == [flagged]
    assert remaining == [unflagged]


def test_csv_partition_is_a_pure_partition_not_a_second_activation_check():
    """This function trusts the cpq_csv_direct flag read_files() already
    set -- it must not re-derive activation from env vars itself, unlike
    partition_cpq_ingestion_plans (XML) which does re-check via
    cpq_ingestion_pipeline_active(). No env vars are set here at all."""
    flagged = {"filename": "catalog.csv", "cpq_csv_direct": True}

    csv_plans, remaining = partition_cpq_ingestion_csv_plans([flagged])

    assert csv_plans == [flagged]
    assert remaining == []


def test_csv_partition_empty_input_returns_empty_outputs():
    assert partition_cpq_ingestion_csv_plans([]) == ([], [])


def test_csv_partition_plan_missing_the_flag_key_entirely_stays_in_remaining():
    plan_without_flag = {"filename": "regular.csv"}

    csv_plans, remaining = partition_cpq_ingestion_csv_plans([plan_without_flag])

    assert csv_plans == []
    assert remaining == [plan_without_flag]


def test_csv_partition_preserves_plan_order_within_each_bucket():
    a = {"filename": "a.csv", "cpq_csv_direct": True}
    b = {"filename": "b.csv"}
    c = {"filename": "c.csv", "cpq_csv_direct": True}
    d = {"filename": "d.csv"}

    csv_plans, remaining = partition_cpq_ingestion_csv_plans([a, b, c, d])

    assert csv_plans == [a, c]
    assert remaining == [b, d]
