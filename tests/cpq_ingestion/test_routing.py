"""cpq_ingestion_pipeline_active — env-var activation matrix."""
from __future__ import annotations

import pytest

from aryx.cpq_ingestion.config import get_cpq_ingestion_settings
from aryx.cpq_ingestion.routing import cpq_ingestion_pipeline_active


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
