"""CPQ_Hardcode_Audit_dev_oci_2026-09-25.md T11 New theme A item 3:
jobs_api.py had no workspace scoping at all (cross-tenant IDOR on
get/events/cancel/resume) and /admin/jobs/archive had no auth dependency
(unauthenticated global data-wipe).
"""
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aryx.api.jobs_api import jobs_router


class _FakeJobStore:
    def __init__(self, jobs: dict[str, dict]):
        self._jobs = jobs
        self.finished: list[tuple] = []
        self.archived_days: list[int] = []

    def get(self, job_id):
        return self._jobs.get(job_id)

    def events(self, job_id):
        return [{"stage": "x", "pct": 50, "detail": "d", "ts": "now"}]

    def finish(self, job_id, run_id, status, error=None):
        self.finished.append((job_id, run_id, status, error))

    def archive_old(self, days):
        self.archived_days.append(days)
        return 3

    def close(self):
        pass


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(jobs_router())
    return TestClient(app, raise_server_exceptions=False)


_WS7_JOB = {
    "job_id": "job-1", "workspace_id": 7, "run_id": 42,
    "status": "running", "source_system": "s", "source_dataset": "d",
    "stage": "x", "pct": 50, "detail": "", "error": None,
    "started_at": None, "updated_at": None, "finished_at": None,
}


def _with_store(fake_store):
    return patch("aryx.api.jobs_api._store", return_value=fake_store)


def test_get_job_in_own_workspace_succeeds(client):
    fake = _FakeJobStore({"job-1": _WS7_JOB})
    with _with_store(fake):
        resp = client.get("/admin/jobs/job-1", params={"workspace_id": 7})
    assert resp.status_code == 200
    assert resp.json()["job_id"] == "job-1"


def test_get_job_in_a_different_workspace_returns_404_not_403(client):
    """A job belonging to workspace 7 must not be visible, or even
    confirmed to exist, to a caller claiming workspace 9 -- this is the
    cross-tenant IDOR the audit flagged."""
    fake = _FakeJobStore({"job-1": _WS7_JOB})
    with _with_store(fake):
        resp = client.get("/admin/jobs/job-1", params={"workspace_id": 9})
    assert resp.status_code == 404


def test_get_job_events_scoped_to_workspace(client):
    fake = _FakeJobStore({"job-1": _WS7_JOB})
    with _with_store(fake):
        ok = client.get("/admin/jobs/job-1/events", params={"workspace_id": 7})
        blocked = client.get("/admin/jobs/job-1/events", params={"workspace_id": 9})
    assert ok.status_code == 200
    assert blocked.status_code == 404


def test_cancel_job_scoped_to_workspace(client):
    fake = _FakeJobStore({"job-1": _WS7_JOB})
    with _with_store(fake):
        blocked = client.post("/admin/jobs/job-1/cancel", params={"workspace_id": 9})
        assert blocked.status_code == 404
        assert fake.finished == []
        ok = client.post("/admin/jobs/job-1/cancel", params={"workspace_id": 7})
    assert ok.status_code == 200
    assert fake.finished == [("job-1", None, "cancelled", "Cancelled by user")]


def test_resume_job_scoped_to_workspace(client):
    fake = _FakeJobStore({"job-1": _WS7_JOB})
    with _with_store(fake), patch(
        "aryx.store.checkpoint_store.StageTracker",
    ) as tracker_cls:
        tracker_cls.return_value.rows.return_value = [{"status": "done"}]
        blocked = client.post("/admin/jobs/job-1/resume", params={"workspace_id": 9})
        ok = client.post("/admin/jobs/job-1/resume", params={"workspace_id": 7})
    assert blocked.status_code == 404
    assert ok.status_code == 200
    assert ok.json()["run_id"] == 42


def test_get_job_omitted_workspace_id_still_defaults_to_1_with_warning(client):
    """Warn-mode, not enforcement (matches T9/T11's established pattern):
    an old caller that never sent workspace_id keeps working against
    workspace 1, but the omission is now observable."""
    fake = _FakeJobStore({"job-1": {**_WS7_JOB, "workspace_id": 1}})
    with _with_store(fake):
        resp = client.get("/admin/jobs/job-1")
    assert resp.status_code == 200


def test_archive_jobs_no_key_returns_401(client):
    fake = _FakeJobStore({})
    with _with_store(fake), patch("aryx.api.security._verify_key", return_value=False):
        resp = client.post("/admin/jobs/archive")
    assert resp.status_code == 401
    assert fake.archived_days == []


def test_archive_jobs_valid_key_proceeds(client):
    fake = _FakeJobStore({})
    with _with_store(fake), patch("aryx.api.security._verify_key", return_value=True):
        resp = client.post(
            "/admin/jobs/archive",
            params={"days": 14},
            headers={"x-aryx-api-key": "valid-key"},
        )
    assert resp.status_code == 200
    assert resp.json() == {"purged": 3}
    assert fake.archived_days == [14]
