"""
Golden-master / characterization tests for app/routes/workspaces.py.

Purpose: tests/test_workspaces.py exercises create_workspace, get_workspace,
list_workspaces, update_workspace, and delete_workspace, but leaves two
endpoints with ZERO coverage (confirmed by reading tests/test_workspaces.py
in full: no reference to "/purge" or "/stats" anywhere in that file):

  - POST /{workspace_id}/purge   (purge_workspace)
  - GET  /{workspace_id}/stats   (get_workspace_stats)

workspaces.py is about to be split into a package (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2). Before the
split, this file captures the CURRENT observable behavior of those two
endpoints so the split can be verified to change nothing.

Note: every test in tests/test_workspaces.py fails already at baseline
(confirmed by running against the pre-split file) with the same root cause:
its `_build_workspace()` helper does `UUID(str(admin_user.company_id))`, and
the `admin_user` fixture's company_id is the non-hex string "company-001" —
a pre-existing test-fixture bug unrelated to this split. This file sidesteps
that helper entirely (workspace mocks here don't coerce company_id to UUID)
so these two endpoints can actually be exercised.

These are characterization tests, not "correctness" tests: assertions match
what the code actually does today, bugs included.

Pattern follows tests/test_channels_characterization.py:
- FastAPI TestClient with `app.include_router(router, prefix=...)`.
- `app.dependency_overrides[get_db] = lambda: mock_db`.
- MagicMock/AsyncMock for services; no real DB, no real HTTP.

Do not modify app/routes/workspaces (the package) from this file's tests.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.database import get_db
from app.routes.workspaces import router

WORKSPACE_ID = "a97c20b0-536d-4017-a171-1ee6d140def0"


def _client(mock_db):
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/workspaces")
    app.dependency_overrides[get_db] = lambda: mock_db
    return TestClient(app, raise_server_exceptions=False)


def _mock_workspace():
    ws = MagicMock()
    ws.id = UUID(WORKSPACE_ID)
    ws.name = "My Workspace"
    ws.description = "Workspace description"
    ws.company_id = uuid4()
    ws.is_active = True
    ws.created_at = datetime.utcnow()
    ws.updated_at = datetime.utcnow()
    return ws


def _scalar_result(value):
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=value)
    result.scalar = MagicMock(return_value=0)
    return result


class _FakeAsyncClient:
    """Minimal async context manager mimicking httpx.AsyncClient for these tests."""

    def __init__(self, get=None, post=None):
        self._get = get or AsyncMock()
        self._post = post or AsyncMock()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def get(self, *args, **kwargs):
        return await self._get(*args, **kwargs)

    async def post(self, *args, **kwargs):
        return await self._post(*args, **kwargs)


# ---------------------------------------------------------------------------
# POST /workspaces/{workspace_id}/purge  (delete_purge.purge_workspace)
# ---------------------------------------------------------------------------
class TestPurgeWorkspace:
    @pytest.mark.unit
    def test_purge_success(self, mock_db, admin_user):
        workspace = _mock_workspace()
        mock_db.execute = AsyncMock(return_value=_scalar_result(workspace))

        mapping_resp = MagicMock()
        mapping_resp.status_code = 200
        mapping_resp.raise_for_status = MagicMock(return_value=None)
        mapping_resp.json = MagicMock(return_value={"aryx_workspace_id": 42})

        purge_resp = MagicMock()
        purge_resp.raise_for_status = MagicMock(return_value=None)
        purge_resp.json = MagicMock(return_value={"status": "purged"})

        fake_client = _FakeAsyncClient(
            get=AsyncMock(return_value=mapping_resp),
            post=AsyncMock(return_value=purge_resp),
        )

        with (
            patch("app.routes.workspaces.purge.get_current_user_required", new=AsyncMock(return_value=admin_user)),
            patch("app.routes.workspaces.purge.require_active_workspace_role", new=AsyncMock(return_value="admin")),
            patch("app.routes.workspaces.purge.httpx.AsyncClient", return_value=fake_client),
            patch("app.routes.workspaces.purge._aryx_headers", return_value={"x-aryx-api-key": "k"}),
        ):
            resp = _client(mock_db).post(f"/api/v1/workspaces/{WORKSPACE_ID}/purge")

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "purged"
        assert body["shay_workspace_id"] == WORKSPACE_ID
        assert body["aryx_workspace_id"] == 42
        assert body["bridge"] == "shay-backend"

    @pytest.mark.unit
    def test_purge_mapping_not_found(self, mock_db, admin_user):
        workspace = _mock_workspace()
        mock_db.execute = AsyncMock(return_value=_scalar_result(workspace))

        mapping_resp = MagicMock()
        mapping_resp.status_code = 404

        fake_client = _FakeAsyncClient(get=AsyncMock(return_value=mapping_resp))

        with (
            patch("app.routes.workspaces.purge.get_current_user_required", new=AsyncMock(return_value=admin_user)),
            patch("app.routes.workspaces.purge.require_active_workspace_role", new=AsyncMock(return_value="admin")),
            patch("app.routes.workspaces.purge.httpx.AsyncClient", return_value=fake_client),
            patch("app.routes.workspaces.purge._aryx_headers", return_value={"x-aryx-api-key": "k"}),
        ):
            resp = _client(mock_db).post(f"/api/v1/workspaces/{WORKSPACE_ID}/purge")

        assert resp.status_code == 404
        assert resp.json()["detail"] == "Workspace bridge mapping not found"

    @pytest.mark.unit
    def test_purge_workspace_not_found(self, mock_db, admin_user):
        mock_db.execute = AsyncMock(return_value=_scalar_result(None))

        with patch(
            "app.routes.workspaces.purge.get_current_user_required",
            new=AsyncMock(return_value=admin_user),
        ):
            resp = _client(mock_db).post(f"/api/v1/workspaces/{WORKSPACE_ID}/purge")

        assert resp.status_code == 404
        assert resp.json()["detail"] == "Workspace not found"


# ---------------------------------------------------------------------------
# GET /workspaces/{workspace_id}/stats  (stats.get_workspace_stats)
# ---------------------------------------------------------------------------
class TestGetWorkspaceStats:
    @pytest.mark.unit
    def test_stats_success(self, mock_db, admin_user):
        workspace = _mock_workspace()

        def _count(n):
            r = MagicMock()
            r.scalar = MagicMock(return_value=n)
            return r

        mock_db.execute = AsyncMock(side_effect=[
            _scalar_result(workspace),  # _get_workspace_or_404
            _count(3),                 # total_threads
            _count(20),                # total_messages
            _count(5),                 # total_attachments
            _count(2),                 # ai_responses_count
        ])

        with (
            patch("app.routes.workspaces.stats.get_current_user_required", new=AsyncMock(return_value=admin_user)),
            patch("app.routes.workspaces.stats.require_active_workspace_role", new=AsyncMock(return_value="admin")),
        ):
            resp = _client(mock_db).get(f"/api/v1/workspaces/{WORKSPACE_ID}/stats")

        assert resp.status_code == 200
        body = resp.json()
        assert body["workspace_id"] == WORKSPACE_ID
        assert body["total_threads"] == 3
        assert body["total_messages"] == 20
        assert body["total_attachments"] == 5
        assert body["ai_responses_count"] == 2
        assert body["last_activity"] is None

    @pytest.mark.unit
    def test_stats_workspace_not_found(self, mock_db, admin_user):
        mock_db.execute = AsyncMock(return_value=_scalar_result(None))

        with patch(
            "app.routes.workspaces.stats.get_current_user_required",
            new=AsyncMock(return_value=admin_user),
        ):
            resp = _client(mock_db).get(f"/api/v1/workspaces/{WORKSPACE_ID}/stats")

        assert resp.status_code == 404
        assert resp.json()["detail"] == "Workspace not found"
