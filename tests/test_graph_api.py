"""Tests for the graph read API overview endpoint."""

from __future__ import annotations

from unittest.mock import patch

import pytest

fastapi = pytest.importorskip("fastapi")
testclient = pytest.importorskip("fastapi.testclient")
FastAPI = fastapi.FastAPI
TestClient = testclient.TestClient


@pytest.fixture
def client() -> TestClient:
    """Minimal FastAPI app with only the graph router."""
    from aryx.api.graph_api import graph_router

    app = FastAPI()
    app.include_router(graph_router())
    return TestClient(app, raise_server_exceptions=False)


def test_graph_overview_returns_domain_focused_payload(client: TestClient) -> None:
    class FakeEntityStore:
        def __init__(self, dsn: str, workspace_id: int = 1) -> None:
            self.workspace_id = workspace_id

        def list_entities(self):
            return iter([
                (1, "SupportTicket", {"name": "Ticket-100"}),
                (2, "SupportTicket", {"name": "Ticket-200"}),
                (3, "Person", {"name": "Alex Agent"}),
            ])

        def list_relationships(self):
            return iter([(1, 2, "RELATED_TO"), (1, 3, "ASSIGNED_TO")])

        def close(self) -> None:
            return None

    class FakeWorkspaceStore:
        def list_all(self):
            return [{"id": 1, "brief": {"domain": "support tickets"}}]

        def close(self) -> None:
            return None

    with (
        patch("aryx.api.graph_api.EntityStore", FakeEntityStore),
        patch("aryx.api.graph_api.make_workspace_store", return_value=FakeWorkspaceStore()),
        patch("aryx.api.graph_api.get_settings") as mock_cfg,
    ):
        mock_cfg.return_value.rdb_dsn = "postgresql://test"
        response = client.get("/graph/overview?workspace_id=1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["domain"] == "support tickets"
    assert payload["fallback_used"] is False
    assert payload["matched_entity_ids"] == [1, 2]
    assert payload["matched_edge_pairs"] == [{"source": 1, "target": 2}]
    assert payload["overview_nodes"][0]["type"] == "SupportTicket"


def test_graph_overview_falls_back_when_domain_has_no_match(client: TestClient) -> None:
    class FakeEntityStore:
        def __init__(self, dsn: str, workspace_id: int = 1) -> None:
            self.workspace_id = workspace_id

        def list_entities(self):
            return iter([
                (1, "Customer", {"name": "Acme"}),
                (2, "Device", {"name": "SM-3000"}),
            ])

        def list_relationships(self):
            return iter([(1, 2, "HAS_DEVICE")])

        def close(self) -> None:
            return None

    class FakeWorkspaceStore:
        def list_all(self):
            return [{"id": 1, "brief": {"domain": "benefits"}}]

        def close(self) -> None:
            return None

    with (
        patch("aryx.api.graph_api.EntityStore", FakeEntityStore),
        patch("aryx.api.graph_api.make_workspace_store", return_value=FakeWorkspaceStore()),
        patch("aryx.api.graph_api.get_settings") as mock_cfg,
    ):
        mock_cfg.return_value.rdb_dsn = "postgresql://test"
        response = client.get("/graph/overview?workspace_id=1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["fallback_used"] is True
    assert payload["matched_entity_ids"] == []
    assert payload["overview_nodes"][0]["type"] == "Customer"
