"""Tests for the /admin/graph/rebuild endpoint."""
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aryx.api.admin_api import admin_router


@pytest.fixture
def client():
    """Minimal FastAPI app with only the admin router — no DB on startup."""
    app = FastAPI()
    app.include_router(admin_router())
    return TestClient(app, raise_server_exceptions=False)


def test_rebuild_graph_no_key_returns_401(client):
    """Endpoint must reject requests with no API key."""
    with patch("aryx.api.security._verify_key", return_value=False):
        resp = client.post("/admin/graph/rebuild")
    assert resp.status_code == 401


def test_rebuild_graph_invalid_key_returns_401(client):
    """Endpoint must reject requests with a bad API key."""
    with patch("aryx.api.security._verify_key", return_value=False):
        resp = client.post(
            "/admin/graph/rebuild",
            headers={"x-aryx-api-key": "bad-key"},
        )
    assert resp.status_code == 401


def test_rebuild_graph_valid_key_returns_ok(client):
    """A valid API key and mocked store calls return status=ok."""
    mock_estore = MagicMock()
    with (
        patch("aryx.api.security._verify_key", return_value=True),
        patch("aryx.api.admin_api.get_settings") as mock_cfg,
        patch("aryx.api.admin_api.EntityStore", return_value=mock_estore),
        patch("aryx.api.admin_api._build_type_ancestors", return_value={}),
        patch(
            "aryx.api.admin_api.project_graph",
            return_value={"nodes": 10, "edges": 5},
        ),
        patch("aryx.api.admin_api.FalkorStore"),
    ):
        mock_cfg.return_value.rdb_dsn = "postgresql://test"
        mock_cfg.return_value.graph_url = "redis://test"
        resp = client.post(
            "/admin/graph/rebuild",
            headers={"x-aryx-api-key": "valid-key"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["workspace_id"] == 1
    assert data["nodes"] == 10
    assert data["edges"] == 5
