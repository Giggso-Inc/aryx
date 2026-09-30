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


def test_layout_inactive_when_pipeline_not_set(monkeypatch):
    monkeypatch.delenv("ARYX_INGEST_PIPELINE", raising=False)
    assert cpq_layout_upload_active("layout.txt") is False


def test_layout_active_for_txt_when_pipeline_set(monkeypatch):
    monkeypatch.setenv("ARYX_INGEST_PIPELINE", "cpq_ingestion")
    assert cpq_layout_upload_active("Config Layout APX Next.txt") is True


def test_layout_active_for_json_when_pipeline_set(monkeypatch):
    monkeypatch.setenv("ARYX_INGEST_PIPELINE", "cpq_ingestion")
    assert cpq_layout_upload_active("layout.json") is True


def test_layout_inactive_for_xml_even_with_pipeline_set(monkeypatch):
    """XML stays on the raw-graph path (cpq_ingestion_pipeline_active),
    never the layout-store path -- the two gates are independent."""
    monkeypatch.setenv("ARYX_INGEST_PIPELINE", "cpq_ingestion")
    assert cpq_layout_upload_active("catalog.xml") is False


def test_layout_active_independent_of_ingest_file_type(monkeypatch):
    """cpq_layout_upload_active does NOT consult ARYX_INGEST_FILE_TYPE --
    it stays XML-specific for cpq_ingestion_pipeline_active, unrelated to
    which files route to the layout store."""
    monkeypatch.setenv("ARYX_INGEST_PIPELINE", "cpq_ingestion")
    monkeypatch.setenv("ARYX_INGEST_FILE_TYPE", "xml")
    assert cpq_layout_upload_active("layout.txt") is True


def test_layout_inactive_for_unrelated_pipeline_value(monkeypatch):
    monkeypatch.setenv("ARYX_INGEST_PIPELINE", "some_other_pipeline")
    assert cpq_layout_upload_active("layout.txt") is False
