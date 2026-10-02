"""_read_job's CPQ layout-file diversion -- CPQ_LAYOUT_FILE_STORAGE_
MIGRATION_PLAN_2026-09-30.md. `.txt`/`.json` layout exports are neither
DOC_EXTS nor DATA_EXTS, so they must be pulled out of `items` before the
extension split, or they're silently dropped (files=0) instead of reaching
read_files() as layout_items -- see doc_discovery.py's own read_files test
for what happens once they get there.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from aryx.api.doc_discover import doc_discover_read_job as read_job_mod


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    from aryx.cpq_ingestion.config import get_cpq_ingestion_settings
    get_cpq_ingestion_settings.cache_clear()
    yield
    get_cpq_ingestion_settings.cache_clear()


def test_read_job_diverts_txt_to_layout_items_when_cpq_layout_active(monkeypatch):
    monkeypatch.setenv("ARYX_INGEST_PIPELINE", "cpq_ingestion")
    monkeypatch.setenv("ARYX_CPQ_LAYOUT_SOURCE", "oracle")

    captured: dict = {}

    def _fake_read_files(doc_paths, tabular, broker, context, **kwargs):
        captured["doc_paths"] = doc_paths
        captured["tabular"] = tabular
        captured["layout_items"] = kwargs.get("layout_items")
        return {"mentions": [], "tabular": [], "summary": {"types": [], "files": []}}

    with patch.object(read_job_mod, "JobStore", lambda dsn: MagicMock()), \
         patch.object(read_job_mod, "_local_broker", lambda: object()), \
         patch.object(read_job_mod, "read_files", _fake_read_files), \
         patch("aryx.discoveries.put"):
        read_job_mod._read_job(
            items=[(b'{"status": "Active"}', "Config Layout APX Next.txt")],
            context="", did="job-1", workspace_id=7,
        )

    assert captured["doc_paths"] == []
    assert captured["tabular"] == []
    assert captured["layout_items"] == [(b'{"status": "Active"}', "Config Layout APX Next.txt")]


def test_read_job_does_not_divert_txt_when_layout_source_flag_missing(monkeypatch):
    """ARYX_INGEST_PIPELINE alone must NOT divert -- matches
    cpq_layout_upload_active()'s own two-flag contract (see
    tests/cpq_ingestion/test_routing.py). A plain .txt with neither flag
    active still falls through both DOC_EXTS/DATA_EXTS untouched (pre-
    existing behavior, out of scope here) -- this test only asserts it does
    NOT get diverted into layout_items."""
    monkeypatch.setenv("ARYX_INGEST_PIPELINE", "cpq_ingestion")
    monkeypatch.delenv("ARYX_CPQ_LAYOUT_SOURCE", raising=False)

    captured: dict = {}

    def _fake_read_files(doc_paths, tabular, broker, context, **kwargs):
        captured["layout_items"] = kwargs.get("layout_items")
        return {"mentions": [], "tabular": [], "summary": {"types": [], "files": []}}

    with patch.object(read_job_mod, "JobStore", lambda dsn: MagicMock()), \
         patch.object(read_job_mod, "_local_broker", lambda: object()), \
         patch.object(read_job_mod, "read_files", _fake_read_files), \
         patch("aryx.discoveries.put"):
        read_job_mod._read_job(
            items=[(b"irrelevant", "Config Layout APX Next.txt")],
            context="", did="job-2", workspace_id=1,
        )

    assert captured["layout_items"] == []


# ── Cancellation: writes must stop once the job row is terminal ────────────
# PR #419 review: POST /admin/jobs/{job_id}/cancel only ever flips the job
# row to 'cancelled' -- nothing in read_files()/extract_mentions() checks
# should_stop, so the worker thread (and this module's own callback/final
# write) kept running and writing regardless. Without this, dismiss()'s
# "cancelled counts as terminal, safe to delete" branch was reachable while
# a still-running read job's next flush would silently re-insert the
# 'pending' row the user just deleted.

def test_on_progress_skips_write_once_job_is_terminal():
    jobs = MagicMock()
    jobs.get.return_value = {"job_id": "job-1", "status": "cancelled"}
    on_progress = read_job_mod._build_read_progress(jobs, "job-1", workspace_id=7)

    with patch("aryx.discoveries.put") as mock_put:
        on_progress(1, 1, [])

    mock_put.assert_not_called()
    jobs.update_stage.assert_not_called()


def test_on_progress_writes_normally_when_job_is_not_terminal():
    jobs = MagicMock()
    jobs.get.return_value = {"job_id": "job-1", "status": "queued"}
    on_progress = read_job_mod._build_read_progress(jobs, "job-1", workspace_id=7)

    with patch("aryx.discoveries.put") as mock_put:
        on_progress(1, 1, [])

    mock_put.assert_called_once()
    jobs.update_stage.assert_called_once()


def test_read_job_final_put_skipped_once_job_is_terminal():
    """Simulates a cancel landing while read_files() was still running:
    by the time it returns, the job row is already 'cancelled' -- the
    final discoveries.put() and jobs.finish(status="complete") must both
    be skipped, not just the periodic on_progress writes."""
    jobs = MagicMock()
    jobs.get.return_value = {"job_id": "job-1", "status": "cancelled"}

    def _fake_read_files(doc_paths, tabular, broker, context, **kwargs):
        return {"mentions": [], "tabular": [], "summary": {"types": [], "files": []}}

    with patch.object(read_job_mod, "JobStore", lambda dsn: jobs), \
         patch.object(read_job_mod, "_local_broker", lambda: object()), \
         patch.object(read_job_mod, "read_files", _fake_read_files), \
         patch("aryx.discoveries.put") as mock_put:
        read_job_mod._read_job(items=[], context="", did="job-1", workspace_id=7)

    mock_put.assert_not_called()
    jobs.finish.assert_not_called()


def test_read_job_final_put_proceeds_when_job_not_terminal():
    jobs = MagicMock()
    jobs.get.return_value = {"job_id": "job-1", "status": "queued"}

    def _fake_read_files(doc_paths, tabular, broker, context, **kwargs):
        return {"mentions": [], "tabular": [], "summary": {"types": [], "files": []}}

    with patch.object(read_job_mod, "JobStore", lambda dsn: jobs), \
         patch.object(read_job_mod, "_local_broker", lambda: object()), \
         patch.object(read_job_mod, "read_files", _fake_read_files), \
         patch("aryx.discoveries.put") as mock_put:
        read_job_mod._read_job(items=[], context="", did="job-1", workspace_id=7)

    mock_put.assert_called_once()
    jobs.finish.assert_called_once_with("job-1", run_id=None, status="complete")
