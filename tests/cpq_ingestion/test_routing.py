"""cpq_ingestion_pipeline_active / cpq_layout_upload_active — env-var
activation matrices."""
from __future__ import annotations

import pytest

from aryx.cpq_ingestion.config import get_cpq_ingestion_settings
from aryx.cpq_ingestion.routing import cpq_ingestion_pipeline_active, cpq_layout_upload_active


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
