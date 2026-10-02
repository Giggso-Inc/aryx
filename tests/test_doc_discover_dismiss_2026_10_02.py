"""POST /admin/docs/{did}/dismiss -- lets a user remove a pending document
discovery from the Ingest page's "waiting to be confirmed" list. Previously
there was no way to dismiss one: DiscoveryStore.drop() existed at the data
layer but no route ever called it.
"""
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aryx.api.doc_discover.doc_discover_api import doc_discover_router


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(doc_discover_router())
    return TestClient(app, raise_server_exceptions=False)


def _with_status(status):
    return patch("aryx.api.doc_discover.doc_discover_api.discoveries.get_status", return_value=status)


def test_dismiss_pending_discovery_succeeds(client):
    with _with_status("pending"), \
         patch("aryx.api.doc_discover.doc_discover_api.discoveries.drop") as mock_drop:
        resp = client.post("/admin/docs/did-1/dismiss", params={"workspace_id": 7})
    assert resp.status_code == 200
    assert resp.json() == {"status": "dismissed"}
    mock_drop.assert_called_once_with("did-1")


def test_dismiss_unknown_discovery_returns_404(client):
    with _with_status(None), \
         patch("aryx.api.doc_discover.doc_discover_api.discoveries.drop") as mock_drop:
        resp = client.post("/admin/docs/missing/dismiss", params={"workspace_id": 7})
    assert resp.status_code == 404
    mock_drop.assert_not_called()


@pytest.mark.parametrize("status", ["confirming", "partial"])
def test_dismiss_in_progress_discovery_returns_409(client, status):
    with _with_status(status), \
         patch("aryx.api.doc_discover.doc_discover_api.discoveries.drop") as mock_drop:
        resp = client.post("/admin/docs/did-1/dismiss", params={"workspace_id": 7})
    assert resp.status_code == 409
    mock_drop.assert_not_called()


def test_dismiss_scoped_to_workspace(client):
    """A discovery in workspace 7 must not be dismissable (or even
    confirmed to exist) by a caller claiming workspace 9 -- same
    cross-tenant IDOR concern as jobs_api.py's cancel/resume routes."""
    def fake_get_status(did, workspace_id):
        return "pending" if workspace_id == 7 else None

    with patch("aryx.api.doc_discover.doc_discover_api.discoveries.get_status", side_effect=fake_get_status), \
         patch("aryx.api.doc_discover.doc_discover_api.discoveries.drop") as mock_drop:
        blocked = client.post("/admin/docs/did-1/dismiss", params={"workspace_id": 9})
        assert blocked.status_code == 404
        assert mock_drop.call_count == 0
        ok = client.post("/admin/docs/did-1/dismiss", params={"workspace_id": 7})
    assert ok.status_code == 200
    mock_drop.assert_called_once_with("did-1")
