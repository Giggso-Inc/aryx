"""CpqIngestionSettings — defaults and env-var overrides."""
from __future__ import annotations

import pytest

from aryx.cpq_ingestion.config import CpqIngestionSettings, get_cpq_ingestion_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_cpq_ingestion_settings.cache_clear()
    yield
    get_cpq_ingestion_settings.cache_clear()


def test_defaults_are_inert_until_explicitly_configured(monkeypatch):
    """Both routing fields default to empty so the pipeline is off by default
    — a fresh deployment must opt in, never silently start rewriting the
    XML-upload path."""
    monkeypatch.delenv("ARYX_INGEST_FILE_TYPE", raising=False)
    monkeypatch.delenv("ARYX_INGEST_PIPELINE", raising=False)
    monkeypatch.delenv("ARYX_CPQ_RAW_GRAPH_ENABLED", raising=False)
    monkeypatch.delenv("ARYX_CPQ_RAW_WORKSPACE_OFFSET", raising=False)
    settings = CpqIngestionSettings()
    assert settings.ingest_file_type == ""
    assert settings.ingest_pipeline == ""
    assert settings.cpq_raw_graph_enabled is True
    assert settings.cpq_raw_workspace_offset == 1_000_000_000


def test_env_vars_override_defaults(monkeypatch):
    monkeypatch.setenv("ARYX_INGEST_FILE_TYPE", "xml")
    monkeypatch.setenv("ARYX_INGEST_PIPELINE", "cpq_ingestion")
    monkeypatch.setenv("ARYX_CPQ_RAW_GRAPH_ENABLED", "false")
    monkeypatch.setenv("ARYX_CPQ_RAW_WORKSPACE_OFFSET", "42")
    settings = CpqIngestionSettings()
    assert settings.ingest_file_type == "xml"
    assert settings.ingest_pipeline == "cpq_ingestion"
    assert settings.cpq_raw_graph_enabled is False
    assert settings.cpq_raw_workspace_offset == 42


def test_get_cpq_ingestion_settings_is_process_wide_cached(monkeypatch):
    monkeypatch.setenv("ARYX_INGEST_FILE_TYPE", "xml")
    first = get_cpq_ingestion_settings()
    monkeypatch.setenv("ARYX_INGEST_FILE_TYPE", "csv")
    second = get_cpq_ingestion_settings()
    assert first is second
    assert second.ingest_file_type == "xml"  # cache not invalidated by the env change alone


def test_unrelated_env_vars_are_ignored_not_rejected(monkeypatch):
    """model_config extra='ignore' -- shared .env file carries unrelated keys
    (SMTP, SSO, ...); this settings class must not fail validation on them."""
    monkeypatch.setenv("ARYX_SOME_UNRELATED_SETTING_THIS_CLASS_DOES_NOT_DEFINE", "whatever")
    CpqIngestionSettings()  # must not raise
