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


def test_cypher_read_uses_server_enforced_read_only_query(client: TestClient) -> None:
    """Regression coverage: this endpoint previously called store.run(), a
    method that never existed on FalkorStore -- every call crashed with
    AttributeError. Now uses run_read_only(), backed by FalkorDB's
    GRAPH.RO_QUERY (server-enforced), not just the keyword blacklist."""
    class FakeStore:
        def __init__(self, url: str, graph: str) -> None:
            pass

        def run_read_only(self, query: str, params: dict) -> list[list[object]]:
            assert query == "MATCH (n) RETURN n LIMIT 1"
            return [[1], [2], [3]]

    with patch("aryx.graph.falkor_store.FalkorStore", FakeStore):
        response = client.post("/graph/cypher", json={
            "query": "MATCH (n) RETURN n LIMIT 1", "limit": 2,
        })

    assert response.status_code == 200
    assert response.json() == {"rows": [[1], [2]]}


def test_cypher_read_rejects_write_keywords(client: TestClient) -> None:
    response = client.post("/graph/cypher", json={"query": "CREATE (n:Entity)"})
    assert response.status_code == 400


def test_cypher_read_rejects_call_procedures(client: TestClient) -> None:
    """CALL can invoke write-capable procedures the original keyword list
    didn't cover; also caught server-side by GRAPH.RO_QUERY regardless."""
    response = client.post("/graph/cypher", json={"query": "CALL db.labels()"})
    assert response.status_code == 400


def test_search_entities_calls_find_entities_with_attrs_by_default() -> None:
    """with_hiding_rules defaults False -- plain find_entities(attrs=...),
    no CpqEngine round-trip."""
    from aryx.api.graph_api import _reader, graph_router

    class FakeReader:
        def find_entities(self, ontology_type=None, name=None, attrs=None, limit=50):
            assert ontology_type == "Product"
            assert attrs == {"Region": "US"}
            return [{"id": 1, "type": "Product", "name": "Widget", "Region": "US"}]

    app = FastAPI()
    app.dependency_overrides[_reader] = lambda: FakeReader()
    app.include_router(graph_router())
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        "/entities/search",
        json={"ontology_type": "Product", "attrs": {"Region": "US"}},
    )

    assert response.status_code == 200
    assert response.json() == [{"id": 1, "type": "Product", "name": "Widget", "Region": "US"}]


def test_search_entities_with_hiding_rules_uses_search_by_feature() -> None:
    """with_hiding_rules=True routes through search_by_feature(), annotating
    each candidate with hidden_by_rule instead of calling find_entities()
    directly."""
    from aryx.api.graph_api import _reader, graph_router

    class FakeReader:
        def find_entities(self, ontology_type=None, name=None, attrs=None, limit=50):
            return [{"id": 1, "type": "Product", "name": "Widget"}]

    with patch("aryx.api.graph_api.search_by_feature") as mock_search:
        mock_search.return_value = [{
            "id": 1, "type": "Product", "name": "Widget",
            "hidden_by_rule": False, "hiding_rule_names": [],
        }]

        app = FastAPI()
        app.dependency_overrides[_reader] = lambda: FakeReader()
        app.include_router(graph_router())
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/entities/search?workspace_id=9",
            json={"name": "Widget", "with_hiding_rules": True, "filled": {"customerType": "Federal"}},
        )

    assert response.status_code == 200
    assert response.json()[0]["hidden_by_rule"] is False
    _, kwargs = mock_search.call_args
    assert mock_search.call_args[0][2] == 9  # workspace_id positional arg
    assert kwargs["name"] == "Widget"
    assert kwargs["filled"] == {"customerType": "Federal"}


def test_search_entities_defaults_are_all_optional() -> None:
    """An empty body (no ontology_type/name/attrs) must still be a valid
    request -- callers may want "all entities up to limit"."""
    from aryx.api.graph_api import _reader, graph_router

    class FakeReader:
        def find_entities(self, ontology_type=None, name=None, attrs=None, limit=50):
            assert ontology_type is None and name is None and attrs is None
            return []

    app = FastAPI()
    app.dependency_overrides[_reader] = lambda: FakeReader()
    app.include_router(graph_router())
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post("/entities/search", json={})

    assert response.status_code == 200
    assert response.json() == []


def test_search_entities_with_region_routes_through_combined_search() -> None:
    """Setting `region` (Phase 2) must route through search_products_
    combined() instead of find_entities/search_by_feature -- the merge
    endpoint, not either half alone."""
    from aryx.api.graph_api import _reader, graph_router

    class FakeReader:
        def find_entities(self, ontology_type=None, name=None, attrs=None, limit=50):
            raise AssertionError("plain find_entities should not be called for a region search")

    with patch("aryx.api.graph_api.search_products_combined") as mock_combined:
        mock_combined.return_value = [{
            "model": "APXNEXTSINGLE", "source": ["data_table"],
            "data_table_matches": [{"model": "APXNEXTSINGLE", "region": "NA"}],
            "graph_entity": None,
        }]

        app = FastAPI()
        app.dependency_overrides[_reader] = lambda: FakeReader()
        app.include_router(graph_router())
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/entities/search?workspace_id=3", json={"region": "NA"},
        )

    assert response.status_code == 200
    assert response.json()[0]["model"] == "APXNEXTSINGLE"
    args, kwargs = mock_combined.call_args
    assert args[2] == 3  # workspace_id positional
    assert kwargs["region"] == "NA"


def test_search_entities_with_feature_label_and_value_routes_through_combined_search() -> None:
    from aryx.api.graph_api import _reader, graph_router

    class FakeReader:
        def find_entities(self, ontology_type=None, name=None, attrs=None, limit=50):
            raise AssertionError("plain find_entities should not be called")

    with patch("aryx.api.graph_api.search_products_combined") as mock_combined:
        mock_combined.return_value = []

        app = FastAPI()
        app.dependency_overrides[_reader] = lambda: FakeReader()
        app.include_router(graph_router())
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/entities/search",
            json={"feature_label": "Feature Type", "feature_value": "Encryption",
                  "cpq_model": "APX1000"},
        )

    assert response.status_code == 200
    _, kwargs = mock_combined.call_args
    assert kwargs["feature_label"] == "Feature Type"
    assert kwargs["feature_value"] == "Encryption"
    assert kwargs["cpq_model"] == "APX1000"


def test_search_entities_feature_value_alone_does_not_trigger_combined_search() -> None:
    """feature_value without feature_label must fall back to the plain
    Phase 1 path -- matches search_products_combined's own guard that a
    partial pair never triggers the Postgres-side search."""
    from aryx.api.graph_api import _reader, graph_router

    class FakeReader:
        def find_entities(self, ontology_type=None, name=None, attrs=None, limit=50):
            return [{"id": 1, "type": "Product", "name": "Widget"}]

    with patch("aryx.api.graph_api.search_products_combined") as mock_combined:
        app = FastAPI()
        app.dependency_overrides[_reader] = lambda: FakeReader()
        app.include_router(graph_router())
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post("/entities/search", json={"feature_value": "Encryption"})

    mock_combined.assert_not_called()
    assert response.status_code == 200
    assert response.json()[0]["name"] == "Widget"


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
