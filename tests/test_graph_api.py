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

        def overview_inputs(self):
            return ([
                (1, "SupportTicket", {"name": "Ticket-100"}),
                (2, "SupportTicket", {"name": "Ticket-200"}),
                (3, "Person", {"name": "Alex Agent"}),
            ], [(1, 2, "RELATED_TO"), (1, 3, "ASSIGNED_TO")], {"domain": "support tickets"})

        def close(self) -> None:
            return None

    with (
        patch("aryx.api.graph_api.EntityStore", FakeEntityStore),
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

        def overview_inputs(self):
            return ([
                (1, "Customer", {"name": "Acme"}),
                (2, "Device", {"name": "SM-3000"}),
            ], [(1, 2, "HAS_DEVICE")], {"domain": "benefits"})

        def close(self) -> None:
            return None

    with (
        patch("aryx.api.graph_api.EntityStore", FakeEntityStore),
        patch("aryx.api.graph_api.get_settings") as mock_cfg,
    ):
        mock_cfg.return_value.rdb_dsn = "postgresql://test"
        response = client.get("/graph/overview?workspace_id=1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["fallback_used"] is True
    assert payload["matched_entity_ids"] == []
    assert payload["overview_nodes"][0]["type"] == "Customer"
    assert payload["overview_nodes"][0]["entity_ids"] == [1]


def test_neighbors_response_includes_direction_field() -> None:
    from aryx.api.graph_api import _reader, graph_router

    class FakeReader:
        def neighbors(self, entity_id: int) -> list[dict[str, object]]:
            assert entity_id == 7
            return [{
                "id": 3,
                "type": "Device",
                "name": "Scanner",
                "relationship": "ASSIGNED_TO",
                "direction": "out",
            }]

    app = FastAPI()
    app.dependency_overrides[_reader] = lambda: FakeReader()
    app.include_router(graph_router())
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/entities/7/neighbors")

    assert response.status_code == 200
    assert response.json() == [{
        "id": 3,
        "type": "Device",
        "name": "Scanner",
        "relationship": "ASSIGNED_TO",
        "direction": "out",
    }]
