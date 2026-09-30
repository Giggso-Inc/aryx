"""CPQ_LAYOUT_FILE_STORAGE_MIGRATION_PLAN_2026-09-30.md: .txt is now an
accepted upload extension (routed to the layout store, never entity
ingestion), and _run_files pulls layout-upload files out of the batch
before the normal _DATA_EXTS/_DOC_EXTS split.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from aryx.api.file_ingest.file_ingest_limits import _ALL, _DATA_EXTS, _LAYOUT_EXTS


def test_txt_is_now_an_accepted_upload_extension():
    assert ".txt" in _ALL


def test_txt_is_not_a_catalog_data_extension():
    """.txt must stay out of _DATA_EXTS -- it's a distinct upload class
    (layout export), never routed through JsonConnector/CsvConnector."""
    assert ".txt" not in _DATA_EXTS
    assert _LAYOUT_EXTS == {".txt"}


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    from aryx.cpq_ingestion.config import get_cpq_ingestion_settings
    get_cpq_ingestion_settings.cache_clear()
    yield
    get_cpq_ingestion_settings.cache_clear()


def test_run_files_routes_txt_upload_to_layout_store_not_entity_ingestion(monkeypatch, tmp_path):
    """A .txt upload under ARYX_INGEST_PIPELINE=cpq_ingestion +
    ARYX_CPQ_LAYOUT_SOURCE (both required) must reach store_layout_file()
    and must never reach run_pipeline()/JsonConnector or the
    datasource-registration loop."""
    monkeypatch.setenv("ARYX_INGEST_PIPELINE", "cpq_ingestion")
    monkeypatch.setenv("ARYX_CPQ_LAYOUT_SOURCE", "oracle")

    from aryx.api.file_ingest import file_ingest_run as run_mod

    stored_calls: list[tuple] = []

    class _FakeJobStore:
        def __init__(self, dsn):
            pass

        def get(self, job_id):
            return {"status": "running"}

        def update_stage(self, job_id, stage, pct, detail):
            pass

        def finish(self, job_id, run_id, status, error=None):
            pass

        def close(self):
            pass

    class _FakeDatasourceStore:
        def __init__(self, dsn):
            self.ensured: list[tuple] = []

        def ensure(self, workspace_id, filename, kind):
            self.ensured.append((workspace_id, filename, kind))

    def _fake_store_layout_file(data, filename, *, workspace_id, dsn, catalog_prefix=None):
        stored_calls.append((filename, workspace_id))
        return catalog_prefix or filename

    with patch.object(run_mod, "JobStore", _FakeJobStore), \
         patch.object(run_mod, "DatasourceStore", _FakeDatasourceStore), \
         patch.object(run_mod, "store_layout_file", _fake_store_layout_file), \
         patch.object(run_mod, "_local_broker", lambda: object()), \
         patch.object(run_mod, "_detect_fk_links", lambda *a, **k: []):
        run_mod._run_files(
            items=[(b'{"status": "Active"}', "Config Layout APX Next.txt")],
            ontology_type="Entity", match_keys=["name"], fk_links=[],
            job_id="job-1", workspace_id=7,
        )

    assert stored_calls == [("Config Layout APX Next.txt", 7)]


def test_run_files_passes_explicit_layout_catalog_prefix_override_through(monkeypatch, tmp_path):
    """CPQ_LAYOUT_FILE_STORAGE_MIGRATION_PLAN_2026-09-30.md 'fix both':
    _run_files' layout_catalog_prefix param must reach store_layout_file()
    as its catalog_prefix kwarg, overriding the filename-derived default."""
    monkeypatch.setenv("ARYX_INGEST_PIPELINE", "cpq_ingestion")
    monkeypatch.setenv("ARYX_CPQ_LAYOUT_SOURCE", "oracle")

    from aryx.api.file_ingest import file_ingest_run as run_mod

    stored_calls: list[tuple] = []

    class _FakeJobStore:
        def __init__(self, dsn):
            pass

        def get(self, job_id):
            return {"status": "running"}

        def update_stage(self, job_id, stage, pct, detail):
            pass

        def finish(self, job_id, run_id, status, error=None):
            pass

        def close(self):
            pass

    class _FakeDatasourceStore:
        def __init__(self, dsn):
            self.ensured: list[tuple] = []

        def ensure(self, workspace_id, filename, kind):
            self.ensured.append((workspace_id, filename, kind))

    def _fake_store_layout_file(data, filename, *, workspace_id, dsn, catalog_prefix=None):
        stored_calls.append((filename, workspace_id, catalog_prefix))
        return catalog_prefix or filename

    with patch.object(run_mod, "JobStore", _FakeJobStore), \
         patch.object(run_mod, "DatasourceStore", _FakeDatasourceStore), \
         patch.object(run_mod, "store_layout_file", _fake_store_layout_file), \
         patch.object(run_mod, "_local_broker", lambda: object()), \
         patch.object(run_mod, "_detect_fk_links", lambda *a, **k: []):
        run_mod._run_files(
            items=[(b'{"status": "Active"}', "Config Layout APX Next.txt")],
            ontology_type="Entity", match_keys=["name"], fk_links=[],
            job_id="job-1", workspace_id=7,
            layout_catalog_prefix="ExplicitPrefix",
        )

    assert stored_calls == [("Config Layout APX Next.txt", 7, "ExplicitPrefix")]


def test_run_files_does_not_divert_txt_when_layout_source_flag_missing(monkeypatch):
    """ARYX_INGEST_PIPELINE=cpq_ingestion alone must NOT divert .txt
    uploads to the layout store -- ARYX_CPQ_LAYOUT_SOURCE is a required
    second opt-in, unlike the XML raw-graph path's single-flag gate."""
    monkeypatch.setenv("ARYX_INGEST_PIPELINE", "cpq_ingestion")
    monkeypatch.delenv("ARYX_CPQ_LAYOUT_SOURCE", raising=False)

    from aryx.cpq_ingestion.routing import cpq_layout_upload_active

    assert cpq_layout_upload_active("Config Layout APX Next.txt") is False
