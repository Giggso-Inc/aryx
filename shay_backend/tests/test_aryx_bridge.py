"""
Unit tests for the Aryx bridge routes (/api/v1/aryx/...) — ask + document
ingestion wired from Shay backend to Aryx's REST API.

All tests are pure-unit: no real DB, no real HTTP to Aryx.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient


def _make_client(mock_db):
    from app.core.database import get_db
    from app.routes.aryx import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/aryx")
    app.dependency_overrides[get_db] = lambda: mock_db
    return TestClient(app, raise_server_exceptions=False)


def _fake_async_client(response=None, post_side_effect=None, get_side_effect=None):
    """Build a MagicMock standing in for `async with httpx.AsyncClient(...) as client`."""
    client = MagicMock()
    if post_side_effect is not None:
        client.post = AsyncMock(side_effect=post_side_effect)
    else:
        client.post = AsyncMock(return_value=response)
    if get_side_effect is not None:
        client.get = AsyncMock(side_effect=get_side_effect)
    else:
        client.get = AsyncMock(return_value=response)
    async_ctx = MagicMock()
    async_ctx.__aenter__ = AsyncMock(return_value=client)
    async_ctx.__aexit__ = AsyncMock(return_value=None)
    return async_ctx, client


def _fake_response(status_code=200, json_body=None, text=""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_body or {}
    resp.text = text
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=resp,
        )
    else:
        resp.raise_for_status.return_value = None
    return resp


_WS_UUID = "550e8400-e29b-41d4-a716-446655440000"


def _patch_access(admin_user, workspace_id=_WS_UUID):
    """Patch the three calls _require_workspace_access makes so any
    authenticated caller with an active role passes the gate."""
    mock_workspace = MagicMock()
    mock_workspace.id = workspace_id
    return (
        patch("app.routes.aryx.get_current_user_required", new=AsyncMock(return_value=admin_user)),
        patch("app.routes.aryx._get_workspace_or_404", new=AsyncMock(return_value=mock_workspace)),
        patch("app.routes.aryx.require_active_workspace_role", new=AsyncMock(return_value="admin")),
    )


@pytest.mark.unit
def test_ask_forwards_question_and_returns_aryx_answer(mock_db, admin_user):
    resp = _fake_response(200, {
        "shay_thread_id": "thread-1", "shay_workspace_id": "ws-1", "aryx_workspace_id": 7,
        "answer": "Revenue grew 12% QoQ.", "terms": ["Revenue"], "tools_called": ["graph_search"],
        "usage": {"input_tokens": 120, "output_tokens": 40},
        "grounding": {"citations": []}, "citations": [],
    })
    async_ctx, client = _fake_async_client(response=resp)
    client_ = _make_client(mock_db)
    p1, p2, p3 = _patch_access(admin_user)

    with p1, p2, p3, \
         patch("app.routes.aryx.httpx.AsyncClient", return_value=async_ctx), \
         patch("app.routes.aryx._aryx_headers", return_value={"x-aryx-api-key": "bridge-key"}):
        response = client_.post(
            "/api/v1/aryx/workspaces/ws-1/ask",
            json={"thread_id": "thread-1", "question": "How did revenue change?"},
            headers={"Authorization": "Bearer test-token"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "Revenue grew 12% QoQ."
    _, kwargs = client.post.await_args
    assert kwargs["json"] == {
        "shay_workspace_id": "ws-1", "shay_thread_id": "thread-1",
        "question": "How did revenue change?",
    }
    assert kwargs["headers"]["x-aryx-api-key"] == "bridge-key"


@pytest.mark.unit
def test_ask_returns_502_when_aryx_unreachable(mock_db, admin_user):
    async_ctx, _ = _fake_async_client(post_side_effect=httpx.RequestError("connection refused"))
    client_ = _make_client(mock_db)
    p1, p2, p3 = _patch_access(admin_user)

    with p1, p2, p3, \
         patch("app.routes.aryx.httpx.AsyncClient", return_value=async_ctx), \
         patch("app.routes.aryx._aryx_headers", return_value={"x-aryx-api-key": "bridge-key"}):
        response = client_.post(
            "/api/v1/aryx/workspaces/ws-1/ask",
            json={"thread_id": "thread-1", "question": "..."},
            headers={"Authorization": "Bearer test-token"},
        )

    assert response.status_code == 502
    assert "Aryx service unavailable" in response.json()["detail"]


@pytest.mark.unit
def test_ask_requires_active_workspace_role(mock_db, admin_user):
    """A caller without an active role in the workspace must be rejected
    before any Aryx call is attempted."""
    client_ = _make_client(mock_db)
    mock_workspace = MagicMock()
    mock_workspace.id = _WS_UUID

    with patch("app.routes.aryx.get_current_user_required", new=AsyncMock(return_value=admin_user)), \
         patch("app.routes.aryx._get_workspace_or_404", new=AsyncMock(return_value=mock_workspace)), \
         patch("app.routes.aryx.require_active_workspace_role",
               new=AsyncMock(side_effect=HTTPException(403, "Access denied to workspace"))):
        response = client_.post(
            "/api/v1/aryx/workspaces/ws-1/ask",
            json={"thread_id": "thread-1", "question": "..."},
            headers={"Authorization": "Bearer test-token"},
        )

    assert response.status_code == 403


@pytest.mark.unit
def test_read_documents_resolves_aryx_workspace_and_uploads_files(mock_db, admin_user):
    mapping_resp = _fake_response(200, {"aryx_workspace_id": 45})
    read_resp = _fake_response(200, {"discovery_id": "disc-123"})
    async_ctx_get, get_client = _fake_async_client(response=mapping_resp)
    async_ctx_post, post_client = _fake_async_client(response=read_resp)

    client_ = _make_client(mock_db)
    p1, p2, p3 = _patch_access(admin_user)

    call_count = {"n": 0}
    def _client_factory(*args, **kwargs):
        call_count["n"] += 1
        return async_ctx_get if call_count["n"] == 1 else async_ctx_post

    with p1, p2, p3, \
         patch("app.routes.aryx.httpx.AsyncClient", side_effect=_client_factory), \
         patch("app.routes.aryx._aryx_headers", return_value={"x-aryx-api-key": "bridge-key"}):
        response = client_.post(
            "/api/v1/aryx/workspaces/ws-1/documents/read",
            files={"files": ("report.csv", b"id,name\n1,Widget\n", "text/csv")},
            data={"context": "Q3 sales report"},
            headers={"Authorization": "Bearer test-token"},
        )

    assert response.status_code == 200
    assert response.json() == {"discovery_id": "disc-123"}
    _, kwargs = post_client.post.await_args
    assert kwargs["data"]["workspace_id"] == "45"
    assert kwargs["data"]["context"] == "Q3 sales report"
    assert kwargs["files"][0][0] == "files"
    assert kwargs["files"][0][1][0] == "report.csv"


@pytest.mark.unit
def test_read_documents_404_when_workspace_never_bridged(mock_db, admin_user):
    mapping_resp = _fake_response(404, {}, text="not found")
    async_ctx, _ = _fake_async_client(response=mapping_resp)
    client_ = _make_client(mock_db)
    p1, p2, p3 = _patch_access(admin_user)

    with p1, p2, p3, \
         patch("app.routes.aryx.httpx.AsyncClient", return_value=async_ctx), \
         patch("app.routes.aryx._aryx_headers", return_value={"x-aryx-api-key": "bridge-key"}):
        response = client_.post(
            "/api/v1/aryx/workspaces/ws-1/documents/read",
            files={"files": ("x.csv", b"a,b\n1,2\n", "text/csv")},
            headers={"Authorization": "Bearer test-token"},
        )

    assert response.status_code == 404
    assert "no Aryx mapping" in response.json()["detail"]


@pytest.mark.unit
def test_document_summary_returns_discovered_types(mock_db, admin_user):
    resp = _fake_response(200, {
        "types": [{"type": "Invoice", "count": 42, "examples": ["INV-001"]}],
        "files": [{"filename": "x.csv", "ontology_type": "Widget"}],
    })
    async_ctx, client = _fake_async_client(response=resp)
    client_ = _make_client(mock_db)
    p1, p2, p3 = _patch_access(admin_user)

    with p1, p2, p3, \
         patch("app.routes.aryx.httpx.AsyncClient", return_value=async_ctx), \
         patch("app.routes.aryx._aryx_headers", return_value={"x-aryx-api-key": "bridge-key"}):
        response = client_.get(
            "/api/v1/aryx/workspaces/ws-1/documents/disc-123/summary",
            headers={"Authorization": "Bearer test-token"},
        )

    assert response.status_code == 200
    assert response.json()["types"][0]["type"] == "Invoice"
    client.get.assert_awaited_once()
    args, _ = client.get.await_args
    assert args[0].endswith("/admin/docs/summary/disc-123")


@pytest.mark.unit
def test_confirm_documents_forwards_approved_types_and_files(mock_db, admin_user):
    resp = _fake_response(200, {"status": "queued", "job_id": "job-456"})
    async_ctx, client = _fake_async_client(response=resp)
    client_ = _make_client(mock_db)
    p1, p2, p3 = _patch_access(admin_user)

    with p1, p2, p3, \
         patch("app.routes.aryx.httpx.AsyncClient", return_value=async_ctx), \
         patch("app.routes.aryx._aryx_headers", return_value={"x-aryx-api-key": "bridge-key"}):
        response = client_.post(
            "/api/v1/aryx/workspaces/ws-1/documents/disc-123/confirm",
            json={"approved_types": ["Invoice", "Customer"], "approved_files": ["x.csv"]},
            headers={"Authorization": "Bearer test-token"},
        )

    assert response.status_code == 200
    assert response.json() == {"status": "queued", "job_id": "job-456"}
    _, kwargs = client.post.await_args
    assert kwargs["json"] == {
        "discovery_id": "disc-123",
        "approved_types": ["Invoice", "Customer"],
        "approved_files": ["x.csv"],
    }


@pytest.mark.unit
def test_job_status_returns_live_progress(mock_db, admin_user):
    resp = _fake_response(200, {
        "job_id": "job-456", "source_system": "discovery", "source_dataset": "1 file(s)",
        "status": "running", "stage": "Reading", "pct": 64, "detail": "Extracted 120/208 chunk(s)…",
        "run_id": None, "error": None, "started_at": "2026-07-27T11:14:43Z",
        "updated_at": "2026-07-27T11:19:52Z", "finished_at": None, "workspace_id": 45,
    })
    async_ctx, _ = _fake_async_client(response=resp)
    client_ = _make_client(mock_db)
    p1, p2, p3 = _patch_access(admin_user)

    with p1, p2, p3, \
         patch("app.routes.aryx.httpx.AsyncClient", return_value=async_ctx), \
         patch("app.routes.aryx._aryx_headers", return_value={"x-aryx-api-key": "bridge-key"}):
        response = client_.get(
            "/api/v1/aryx/workspaces/ws-1/jobs/job-456",
            headers={"Authorization": "Bearer test-token"},
        )

    assert response.status_code == 200
    assert response.json()["pct"] == 64


@pytest.mark.unit
def test_job_status_404_when_job_unknown(mock_db, admin_user):
    resp = _fake_response(404, {}, text="job not found")
    async_ctx, _ = _fake_async_client(response=resp)
    client_ = _make_client(mock_db)
    p1, p2, p3 = _patch_access(admin_user)

    with p1, p2, p3, \
         patch("app.routes.aryx.httpx.AsyncClient", return_value=async_ctx), \
         patch("app.routes.aryx._aryx_headers", return_value={"x-aryx-api-key": "bridge-key"}):
        response = client_.get(
            "/api/v1/aryx/workspaces/ws-1/jobs/does-not-exist",
            headers={"Authorization": "Bearer test-token"},
        )

    assert response.status_code == 404
