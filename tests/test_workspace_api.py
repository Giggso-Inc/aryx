"""Tests for the Aryx workspace admin API."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Minimal FastAPI app with only the workspace router."""
    from aryx.api.workspace_api import workspace_router

    app = FastAPI()
    app.include_router(workspace_router())
    return TestClient(app, raise_server_exceptions=False)


def test_update_workspace_metadata_calls_store(client):
    class FakeStore:
        def close(self):
            return None

        def update_metadata(self, workspace_id, *, name=None, description=None):
            assert workspace_id == 7
            assert name == "Renamed"
            assert description == "Updated description"
            return {
                "id": 7,
                "name": name,
                "description": description,
                "context": "",
                "brief": {},
                "created_at": "2026-07-01T00:00:00",
            }

    with (
        patch("aryx.api.workspace_api.apply_migrations"),
        patch("aryx.api.workspace_api.WorkspaceStore", return_value=FakeStore()),
    ):
        response = client.put(
            "/admin/workspaces/7",
            json={"name": "Renamed", "description": "Updated description"},
        )

    assert response.status_code == 200
    assert response.json()["name"] == "Renamed"
    assert response.json()["description"] == "Updated description"


def test_update_workspace_metadata_returns_404_when_missing(client):
    class FakeStore:
        def close(self):
            return None

        def update_metadata(self, workspace_id, *, name=None, description=None):
            raise ValueError(f"workspace {workspace_id} not found")

    with (
        patch("aryx.api.workspace_api.apply_migrations"),
        patch("aryx.api.workspace_api.WorkspaceStore", return_value=FakeStore()),
    ):
        response = client.put(
            "/admin/workspaces/77",
            json={"name": "Missing"},
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "workspace 77 not found"
