"""POST /admin/docs/{did}/dismiss -- lets a user remove a pending document
discovery from the Ingest page's "waiting to be confirmed" list.

2026-10-02 review of the first version of this route found three issues,
all fixed here:

1. (red, must-fix) A dismissed discovery reappeared if its read job was
   still running: _build_read_progress keeps calling discoveries.put()
   after every chunk, which upserts the row back to status='pending'
   (put()'s ON CONFLICT never touches status, so a fresh INSERT after a
   delete always lands 'pending'). Fixed by checking the read job's own
   status (it uses `did` as its job_id) before attempting the delete.
2. (orange) get_status()-then-drop() had a TOCTOU race: /confirm could flip
   the row to 'confirming' between the two calls, and the unconditional
   drop() deleted it anyway, orphaning the confirm job. Fixed by folding
   the status check into the DELETE's WHERE clause (drop_if_pending),
   making "is it still pending" and "delete it" atomic.
3. (yellow, free with #2) The old code blocklisted ("confirming", "partial")
   instead of allowlisting "pending" -- a 'confirmed' row (deleting that
   destroys real ingest history) fell through and was dismissable.
   drop_if_pending's WHERE status='pending' only ever matches pending rows.
"""
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aryx.api.doc_discover.doc_discover_api import doc_discover_router


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(doc_discover_router())
    return TestClient(app, raise_server_exceptions=False)


def _with_job(job):
    """job=None simulates no read job (or one already purged); a dict
    simulates JobStore.get(did)'s return shape."""
    mock_jobs = MagicMock()
    mock_jobs.get.return_value = job
    return patch("aryx.api.doc_discover.doc_discover_api.JobStore", return_value=mock_jobs)


def _with_drop_if_pending(deleted: bool):
    return patch("aryx.api.doc_discover.doc_discover_api.discoveries.drop_if_pending", return_value=deleted)


def _with_status(status):
    return patch("aryx.api.doc_discover.doc_discover_api.discoveries.get_status", return_value=status)


def test_dismiss_pending_discovery_succeeds(client):
    with _with_job(None), _with_drop_if_pending(True) as mock_drop:
        resp = client.post("/admin/docs/did-1/dismiss", params={"workspace_id": 7})
    assert resp.status_code == 200
    assert resp.json() == {"status": "dismissed"}
    mock_drop.assert_called_once_with("did-1", 7)


def test_dismiss_unknown_discovery_returns_404(client):
    with _with_job(None), _with_drop_if_pending(False), _with_status(None):
        resp = client.post("/admin/docs/missing/dismiss", params={"workspace_id": 7})
    assert resp.status_code == 404


@pytest.mark.parametrize("status", ["confirming", "partial", "confirmed"])
def test_dismiss_non_pending_status_returns_409(client, status):
    """Allowlist (only 'pending' is ever eligible, via drop_if_pending's own
    WHERE clause), not a blocklist -- 'confirmed' must be just as protected
    as 'confirming'/'partial', unlike the original version of this route."""
    with _with_job(None), _with_drop_if_pending(False), _with_status(status):
        resp = client.post("/admin/docs/did-1/dismiss", params={"workspace_id": 7})
    assert resp.status_code == 409
    assert status in resp.json()["detail"]


def test_dismiss_while_read_job_still_running_returns_409_without_deleting(client):
    """Must-fix finding: a running read job (status='queued', it never
    transitions to anything else until finish()) keeps re-upserting the
    discovery row to 'pending' after every progress chunk -- dismissing
    while that's happening would just get silently undone moments later.
    drop_if_pending must never even be attempted in this case."""
    job = {"job_id": "did-1", "workspace_id": 7, "status": "queued"}
    with _with_job(job), _with_drop_if_pending(True) as mock_drop:
        resp = client.post("/admin/docs/did-1/dismiss", params={"workspace_id": 7})
    assert resp.status_code == 409
    assert "read job" in resp.json()["detail"]
    mock_drop.assert_not_called()


@pytest.mark.parametrize("terminal_status", ["complete", "failed", "cancelled"])
def test_dismiss_after_read_job_finished_proceeds_normally(client, terminal_status):
    """Once the read job reaches any terminal status, it will never write to
    the discovery row again -- dismiss must proceed exactly as if there were
    no job check at all."""
    job = {"job_id": "did-1", "workspace_id": 7, "status": terminal_status}
    with _with_job(job), _with_drop_if_pending(True) as mock_drop:
        resp = client.post("/admin/docs/did-1/dismiss", params={"workspace_id": 7})
    assert resp.status_code == 200
    mock_drop.assert_called_once_with("did-1", 7)


def test_dismiss_read_job_in_a_different_workspace_is_ignored(client):
    """A job row that happens to share the discovery_id as its job_id but
    belongs to a DIFFERENT workspace must not block this caller's dismiss --
    JobStore.get() itself isn't workspace-scoped, so the route must compare
    workspace_id itself rather than trusting the job row blindly."""
    job = {"job_id": "did-1", "workspace_id": 9, "status": "queued"}
    with _with_job(job), _with_drop_if_pending(True) as mock_drop:
        resp = client.post("/admin/docs/did-1/dismiss", params={"workspace_id": 7})
    assert resp.status_code == 200
    mock_drop.assert_called_once_with("did-1", 7)


def test_dismiss_toctou_race_is_closed_by_a_single_conditional_delete(client):
    """Orange finding: the route must call drop_if_pending (one atomic
    conditional DELETE), never a separate get_status() followed by an
    unconditional drop() -- that two-step shape is exactly the TOCTOU
    window /confirm could land in. Asserting discoveries.drop is never
    even imported/called confirms the old code path is gone, not just
    patched over in this test."""
    with _with_job(None), _with_drop_if_pending(True) as mock_drop, \
         patch("aryx.api.doc_discover.doc_discover_api.discoveries.drop") as mock_unconditional_drop:
        resp = client.post("/admin/docs/did-1/dismiss", params={"workspace_id": 7})
    assert resp.status_code == 200
    mock_drop.assert_called_once()
    mock_unconditional_drop.assert_not_called()


def test_dismiss_omitted_workspace_id_defaults_to_1_with_warning(client):
    """Low finding: this destructive route used a bare `workspace_id: int
    = 1` default instead of the resolve_workspace_id_warn() convention
    PR #391/#401 established for mutating routes -- a caller that forgot
    the param silently acted on workspace 1 with no way to audit it later.
    Warn-mode, not enforcement: an old/forgetful caller keeps working
    against workspace 1, but the omission is now observable (logged)."""
    with _with_job(None), _with_drop_if_pending(True) as mock_drop:
        resp = client.post("/admin/docs/did-1/dismiss")
    assert resp.status_code == 200
    mock_drop.assert_called_once_with("did-1", 1)


def test_dismiss_scoped_to_workspace(client):
    """A discovery in workspace 7 must not be dismissable (or even
    confirmed to exist) by a caller claiming workspace 9 -- same
    cross-tenant IDOR concern as jobs_api.py's cancel/resume routes."""
    def fake_drop_if_pending(did, workspace_id):
        return workspace_id == 7

    def fake_get_status(did, workspace_id):
        return "pending" if workspace_id == 7 else None

    with _with_job(None), \
         patch("aryx.api.doc_discover.doc_discover_api.discoveries.drop_if_pending",
               side_effect=fake_drop_if_pending) as mock_drop, \
         patch("aryx.api.doc_discover.doc_discover_api.discoveries.get_status",
               side_effect=fake_get_status):
        blocked = client.post("/admin/docs/did-1/dismiss", params={"workspace_id": 9})
        assert blocked.status_code == 404
        ok = client.post("/admin/docs/did-1/dismiss", params={"workspace_id": 7})
    assert ok.status_code == 200
    assert mock_drop.call_count == 2
