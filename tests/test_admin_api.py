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


def test_rebuild_graph_falkordb_backend_uses_falkorstore(client):
    """Explicit non-oci_graph backend still takes the FalkorStore path."""
    mock_estore = MagicMock()
    with (
        patch("aryx.api.security._verify_key", return_value=True),
        patch("aryx.api.admin_api.get_settings") as mock_cfg,
        patch("aryx.api.admin_api.EntityStore", return_value=mock_estore),
        patch("aryx.api.admin_api._build_type_ancestors", return_value={}),
        patch(
            "aryx.api.admin_api.project_graph",
            return_value={"nodes": 1, "edges": 0},
        ) as mock_project_graph,
        patch("aryx.api.admin_api.FalkorStore") as mock_falkor,
    ):
        mock_cfg.return_value.rdb_dsn = "postgresql://test"
        mock_cfg.return_value.graph_url = "redis://test"
        mock_cfg.return_value.effective_graph_backend.return_value = "falkordb"
        resp = client.post(
            "/admin/graph/rebuild",
            headers={"x-aryx-api-key": "valid-key"},
        )

    assert resp.status_code == 200
    mock_falkor.assert_called_once()
    assert mock_project_graph.call_args[0][1] is mock_falkor.return_value


def test_rebuild_graph_oci_graph_backend_uses_oracle_graph_store(client):
    """CPQ_Hardcode_Audit_dev_oci_2026-09-25.md T11 follow-up: an
    ARYX_GRAPH_BACKEND=oci_graph deployment must rebuild the Oracle graph,
    not silently rebuild an unused FalkorStore graph nothing reads from."""
    mock_estore = MagicMock()
    mock_oracle_store = MagicMock()
    with (
        patch("aryx.api.security._verify_key", return_value=True),
        patch("aryx.api.admin_api.get_settings") as mock_cfg,
        patch("aryx.api.admin_api.EntityStore", return_value=mock_estore),
        patch("aryx.api.admin_api._build_type_ancestors", return_value={}),
        patch(
            "aryx.api.admin_api.project_graph",
            return_value={"nodes": 204491, "edges": 1522635},
        ) as mock_project_graph,
        patch("aryx.api.admin_api.FalkorStore") as mock_falkor,
        patch(
            "aryx.graph.oracle_graph_store.OracleGraphStore",
            return_value=mock_oracle_store,
        ) as mock_oracle_cls,
    ):
        mock_cfg.return_value.rdb_dsn = "postgresql://test"
        mock_cfg.return_value.oci_adb_dsn = "tcps://test:1522/db"
        mock_cfg.return_value.effective_graph_backend.return_value = "oci_graph"
        resp = client.post(
            "/admin/graph/rebuild?workspace_id=704",
            headers={"x-aryx-api-key": "valid-key"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["nodes"] == 204491
    mock_oracle_cls.assert_called_once_with("tcps://test:1522/db", 704)
    mock_falkor.assert_not_called()
    assert mock_project_graph.call_args[0][1] is mock_oracle_store


def test_rebuild_graph_oci_graph_backend_missing_dep_returns_503(client):
    """ARYX_GRAPH_BACKEND=oci_graph without the OCI extras installed must
    fail loudly (503), not silently fall back to rebuilding the wrong graph."""
    mock_estore = MagicMock()
    with (
        patch("aryx.api.security._verify_key", return_value=True),
        patch("aryx.api.admin_api.get_settings") as mock_cfg,
        patch("aryx.api.admin_api.EntityStore", return_value=mock_estore),
        patch("aryx.api.admin_api._build_type_ancestors", return_value={}),
        patch("aryx.api.admin_api.FalkorStore") as mock_falkor,
    ):
        mock_cfg.return_value.rdb_dsn = "postgresql://test"
        mock_cfg.return_value.oci_adb_dsn = "tcps://test:1522/db"
        mock_cfg.return_value.effective_graph_backend.return_value = "oci_graph"
        import sys
        with patch.dict(sys.modules, {"aryx.graph.oracle_graph_store": None}):
            resp = client.post(
                "/admin/graph/rebuild?workspace_id=704",
                headers={"x-aryx-api-key": "valid-key"},
            )

    assert resp.status_code == 503
    mock_falkor.assert_not_called()
