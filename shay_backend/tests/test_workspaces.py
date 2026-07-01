"""
Unit tests for Shay workspace CRUD routes.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _make_client(mock_db):
    from app.core.database import get_db
    from app.routes.workspaces import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/workspaces")
    app.dependency_overrides[get_db] = lambda: mock_db
    return TestClient(app, raise_server_exceptions=False)


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
    assert kwargs["headers"]["Authorization"] == "Bearer test-token"
