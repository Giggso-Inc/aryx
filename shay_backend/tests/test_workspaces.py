"""
Unit tests for Shay workspace CRUD routes.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient


def _make_client(mock_db):
    from app.core.database import get_db
    from app.routes.workspaces import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/workspaces")
    app.dependency_overrides[get_db] = lambda: mock_db
    return TestClient(app, raise_server_exceptions=False)


def _build_workspace(admin_user, workspace_id: str):
    mock_workspace = MagicMock()
    mock_workspace.id = UUID(workspace_id)
    mock_workspace.name = "My Workspace"
    mock_workspace.description = "Workspace description"
    mock_workspace.company_id = UUID(str(admin_user.company_id))
    mock_workspace.is_active = True
    mock_workspace.is_public = False
    mock_workspace.ai_enabled = True
    mock_workspace.ai_provider = "openai"
    mock_workspace.ai_model = "gpt-4"
    mock_workspace.max_messages = "1000"
    mock_workspace.max_attachments = "100"
    mock_workspace.workspace_type = "aryx"
    mock_workspace.user_id = UUID(str(admin_user.id))
    mock_workspace.created_by = UUID(str(admin_user.id))
    mock_workspace.settings = {}
    mock_workspace.created_at = datetime.utcnow()
    mock_workspace.updated_at = datetime.utcnow()
    mock_workspace.is_accessible_by_user.return_value = True
    return mock_workspace


@pytest.mark.unit
def test_create_workspace_triggers_aryx_bridge_after_shay_create(mock_db, admin_user):
    from app.routes import workspaces as workspaces_route

    mock_workspace = MagicMock()
    mock_workspace.id = "workspace-123"
    mock_workspace.name = "My Workspace"
    mock_workspace.description = "Workspace description"
    mock_workspace.company_id = "company-001"

    fake_client = MagicMock()
    fake_response = MagicMock()
    fake_response.json.return_value = {
        "shay_workspace_id": "workspace-123",
        "aryx_workspace_id": 7,
        "company_id": "company-001",
        "created": True,
    }
    fake_response.raise_for_status.return_value = None
    fake_client.post = AsyncMock(return_value=fake_response)
    fake_async_client = MagicMock()
    fake_async_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_async_client.__aexit__ = AsyncMock(return_value=None)

    client = _make_client(mock_db)

    with (
        patch("app.routes.workspaces.get_current_user_required", new=AsyncMock(return_value=admin_user)),
        patch("app.routes.workspaces.generate_workspace_id", return_value="workspace-123"),
        patch("app.routes.workspaces.ensure_workspace_membership", new=AsyncMock()),
        patch("app.routes.workspaces.httpx.AsyncClient", return_value=fake_async_client),
        patch.object(workspaces_route.settings, "ARYX_API_URL_INTERNAL", "http://aryx-internal"),
        patch.object(workspaces_route.settings, "ARYX_INTERNAL_API_KEY", "bridge-key"),
    ):
        response = client.post(
            "/api/v1/workspaces/",
            json={
                "name": "My Workspace",
                "description": "Workspace description",
                "workspace_type": "aryx",
            },
            headers={"Authorization": "Bearer test-token"},
        )

    assert response.status_code == 200
    assert response.json()["id"] == "workspace-123"
    fake_client.post.assert_awaited_once()
    _, kwargs = fake_client.post.await_args
    assert kwargs["json"] == {
        "shay_workspace_id": "workspace-123",
        "name": "My Workspace",
        "description": "Workspace description",
        "company_id": "company-001",
    }
    assert kwargs["headers"]["x-aryx-api-key"] == "bridge-key"


@pytest.mark.unit
def test_get_workspace_coerces_workspace_id_to_uuid_before_query(mock_db, admin_user):
    workspace_id = "a97c20b0-536d-4017-a171-1ee6d140def0"
    captured = {}
    mock_workspace = _build_workspace(admin_user, workspace_id)

    class _Result:
        def scalar_one_or_none(self):
            return mock_workspace

    async def execute(stmt):
        captured["workspace_id_type"] = type(list(stmt._where_criteria)[0].right.value)
        return _Result()

    mock_db.execute = execute
    client = _make_client(mock_db)

    with (
        patch("app.routes.workspaces.get_current_user_required", new=AsyncMock(return_value=admin_user)),
        patch("app.routes.workspaces._bridge_for_workspace", new=AsyncMock(return_value={"aryx_workspace_id": 7})),
    ):
        response = client.get(
            f"/api/v1/workspaces/{workspace_id}",
            headers={"Authorization": "Bearer test-token"},
        )

    assert response.status_code == 200
    assert captured["workspace_id_type"] is UUID


@pytest.mark.unit
def test_create_workspace_rolls_back_when_aryx_bridge_fails(mock_db, admin_user):
    from app.routes import workspaces as workspaces_route

    fake_client = MagicMock()
    fake_client.post = AsyncMock(side_effect=httpx.RequestError("bridge down"))
    fake_async_client = MagicMock()
    fake_async_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_async_client.__aexit__ = AsyncMock(return_value=None)

    client = _make_client(mock_db)

    with (
        patch("app.routes.workspaces.get_current_user_required", new=AsyncMock(return_value=admin_user)),
        patch("app.routes.workspaces.generate_workspace_id", return_value="workspace-123"),
        patch("app.routes.workspaces.ensure_workspace_membership", new=AsyncMock()),
        patch("app.routes.workspaces.httpx.AsyncClient", return_value=fake_async_client),
        patch.object(workspaces_route.settings, "ARYX_API_URL_INTERNAL", "http://aryx-internal"),
        patch.object(workspaces_route.settings, "ARYX_INTERNAL_API_KEY", "bridge-key"),
    ):
        response = client.post(
            "/api/v1/workspaces/",
            json={
                "name": "My Workspace",
                "description": "Workspace description",
                "workspace_type": "aryx",
            },
            headers={"Authorization": "Bearer test-token"},
        )

    assert response.status_code == 502
    mock_db.rollback.assert_awaited_once()
    mock_db.commit.assert_not_awaited()


@pytest.mark.unit
def test_list_workspaces_filters_to_active_memberships(mock_db, admin_user):
    workspace_id = "a97c20b0-536d-4017-a171-1ee6d140def0"
    captured = {}
    mock_workspace = _build_workspace(admin_user, workspace_id)

    class _WorkspaceResult:
        def scalars(self):
            return MagicMock(all=MagicMock(return_value=[mock_workspace]))

    class _CountResult:
        def scalar(self):
            return 1

    async def execute(stmt):
        text = str(stmt).lower()
        if "count(" in text:
            captured["count_query"] = text
            return _CountResult()
        captured["list_query"] = text
        return _WorkspaceResult()

    mock_db.execute = execute
    client = _make_client(mock_db)

    with (
        patch("app.routes.workspaces.get_current_user_required", new=AsyncMock(return_value=admin_user)),
        patch("app.routes.workspaces._bridge_for_workspace", new=AsyncMock(return_value={"aryx_workspace_id": 7})),
    ):
        response = client.get(
            "/api/v1/workspaces/",
            headers={"Authorization": "Bearer test-token"},
        )

    assert response.status_code == 200
    assert "gg_members" in captured["list_query"]
    assert "gg_members" in captured["count_query"]
    assert "is_active" in captured["list_query"]
    assert response.json()["total"] == 1


@pytest.mark.unit
def test_get_workspace_denies_removed_member(mock_db, regular_user):
    workspace_id = "a97c20b0-536d-4017-a171-1ee6d140def0"
    mock_workspace = _build_workspace(regular_user, workspace_id)

    class _Result:
        def scalar_one_or_none(self):
            return mock_workspace

    async def execute(_stmt):
        return _Result()

    mock_db.execute = execute
    client = _make_client(mock_db)

    with (
        patch("app.routes.workspaces.get_current_user_required", new=AsyncMock(return_value=regular_user)),
        patch(
            "app.routes.workspaces.require_active_workspace_role",
            new=AsyncMock(side_effect=HTTPException(status_code=403, detail="Access denied to workspace")),
        ),
    ):
        response = client.get(
            f"/api/v1/workspaces/{workspace_id}",
            headers={"Authorization": "Bearer test-token"},
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "Access denied to workspace"


@pytest.mark.unit
def test_update_workspace_coerces_workspace_id_to_uuid_before_query(mock_db, admin_user):
    workspace_id = "a97c20b0-536d-4017-a171-1ee6d140def0"
    captured = {}
    mock_workspace = _build_workspace(admin_user, workspace_id)

    class _Result:
        def scalar_one_or_none(self):
            return mock_workspace

    async def execute(stmt):
        captured["workspace_id_type"] = type(list(stmt._where_criteria)[0].right.value)
        return _Result()

    mock_db.execute = execute
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()
    client = _make_client(mock_db)
    aryx_sync = AsyncMock(return_value={"id": 7, "name": "Updated Workspace"})

    with (
        patch("app.routes.workspaces.get_current_user_required", new=AsyncMock(return_value=admin_user)),
        patch("app.routes.workspaces.require_active_workspace_role", new=AsyncMock(return_value="admin")),
        patch("app.routes.workspaces._bridge_for_workspace", new=AsyncMock(return_value={"aryx_workspace_id": 7})),
        patch("app.routes.workspaces._update_aryx_workspace_bridge", new=aryx_sync),
    ):
        response = client.put(
            f"/api/v1/workspaces/{workspace_id}",
            json={"name": "Updated Workspace"},
            headers={"Authorization": "Bearer test-token"},
        )

    assert response.status_code == 200
    assert captured["workspace_id_type"] is UUID
    assert mock_workspace.name == "Updated Workspace"
    mock_db.commit.assert_awaited_once()
    mock_db.refresh.assert_awaited_once_with(mock_workspace)
    aryx_sync.assert_awaited_once_with(ANY, 7, mock_workspace)


@pytest.mark.unit
def test_delete_workspace_coerces_workspace_id_to_uuid_before_query(mock_db, admin_user):
    workspace_id = "a97c20b0-536d-4017-a171-1ee6d140def0"
    captured = {}
    mock_workspace = _build_workspace(admin_user, workspace_id)

    class _Result:
        def scalar_one_or_none(self):
            return mock_workspace

    async def execute(stmt):
        captured["workspace_id_type"] = type(list(stmt._where_criteria)[0].right.value)
        return _Result()

    mock_db.execute = execute
    mock_db.delete = AsyncMock()
    mock_db.commit = AsyncMock()
    client = _make_client(mock_db)

    fake_client = MagicMock()
    fake_mapping_response = MagicMock()
    fake_mapping_response.status_code = 404
    fake_client.get = AsyncMock(return_value=fake_mapping_response)
    fake_async_client = MagicMock()
    fake_async_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_async_client.__aexit__ = AsyncMock(return_value=None)

    with (
        patch("app.routes.workspaces.get_current_user_required", new=AsyncMock(return_value=admin_user)),
        patch("app.routes.workspaces.require_active_workspace_role", new=AsyncMock(return_value="admin")),
        patch("app.routes.workspaces.httpx.AsyncClient", return_value=fake_async_client),
        patch("app.routes.workspaces._delete_aryx_workspace_bridge", new=AsyncMock()),
        patch("app.routes.workspaces._aryx_headers", return_value={"x-aryx-api-key": "bridge-key"}),
    ):
        response = client.delete(
            f"/api/v1/workspaces/{workspace_id}",
            headers={"Authorization": "Bearer test-token"},
        )

    assert response.status_code == 200
    assert captured["workspace_id_type"] is UUID
    mock_db.delete.assert_awaited_once_with(mock_workspace)
    mock_db.commit.assert_awaited_once()
