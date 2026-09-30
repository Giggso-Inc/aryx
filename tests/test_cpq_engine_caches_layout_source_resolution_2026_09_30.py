"""_resolve_layout_file_source -- the combined
(ARYX_INGEST_PIPELINE, ARYX_CPQ_LAYOUT_SOURCE) flag matrix from
CPQ_LAYOUT_FILE_STORAGE_MIGRATION_PLAN_2026-09-30.md §4.3. Mirrors
ARYX_CPQ_RAW_GRAPH_ENABLED's existing nesting: the fine-grained flag
(ARYX_CPQ_LAYOUT_SOURCE) only takes effect once the outer master switch
(ARYX_INGEST_PIPELINE=cpq_ingestion) has already said yes.
"""
from __future__ import annotations

import pytest

from aryx.cpq.engine_caches import _resolve_layout_file_source
from aryx.cpq.layout_source import LocalDirLayoutFileSource, OracleLayoutFileSource
from aryx.cpq_ingestion.config import get_cpq_ingestion_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_cpq_ingestion_settings.cache_clear()
    yield
    get_cpq_ingestion_settings.cache_clear()


def test_neither_flag_set_stays_local(monkeypatch):
    monkeypatch.delenv("ARYX_INGEST_PIPELINE", raising=False)
    monkeypatch.delenv("ARYX_CPQ_LAYOUT_SOURCE", raising=False)
    assert isinstance(_resolve_layout_file_source(), LocalDirLayoutFileSource)


def test_layout_source_oracle_alone_without_master_switch_stays_local(monkeypatch):
    """ARYX_CPQ_LAYOUT_SOURCE=oracle alone (pipeline not cpq_ingestion)
    must NOT activate the Oracle backend -- same nesting requirement as
    ARYX_CPQ_RAW_GRAPH_ENABLED."""
    monkeypatch.delenv("ARYX_INGEST_PIPELINE", raising=False)
    monkeypatch.setenv("ARYX_CPQ_LAYOUT_SOURCE", "oracle")
    assert isinstance(_resolve_layout_file_source(), LocalDirLayoutFileSource)


def test_master_switch_alone_without_layout_source_stays_local(monkeypatch):
    monkeypatch.setenv("ARYX_INGEST_PIPELINE", "cpq_ingestion")
    monkeypatch.delenv("ARYX_CPQ_LAYOUT_SOURCE", raising=False)
    assert isinstance(_resolve_layout_file_source(), LocalDirLayoutFileSource)


def test_both_flags_set_activates_oracle(monkeypatch):
    monkeypatch.setattr("aryx.store.pool.get_pool", lambda dsn: object())
    monkeypatch.setenv("ARYX_INGEST_PIPELINE", "cpq_ingestion")
    monkeypatch.setenv("ARYX_CPQ_LAYOUT_SOURCE", "oracle")
    assert isinstance(_resolve_layout_file_source(), OracleLayoutFileSource)


def test_both_flags_set_case_insensitive(monkeypatch):
    monkeypatch.setattr("aryx.store.pool.get_pool", lambda dsn: object())
    monkeypatch.setenv("ARYX_INGEST_PIPELINE", "CPQ_Ingestion")
    monkeypatch.setenv("ARYX_CPQ_LAYOUT_SOURCE", "ORACLE")
    assert isinstance(_resolve_layout_file_source(), OracleLayoutFileSource)


def test_unrelated_pipeline_value_with_layout_source_oracle_stays_local(monkeypatch):
    monkeypatch.setenv("ARYX_INGEST_PIPELINE", "some_other_pipeline")
    monkeypatch.setenv("ARYX_CPQ_LAYOUT_SOURCE", "oracle")
    assert isinstance(_resolve_layout_file_source(), LocalDirLayoutFileSource)
