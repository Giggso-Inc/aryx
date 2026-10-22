"""Regression tests for the parameterized external Cypher endpoint."""
from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

# The route test replaces GraphReader, so it must not require a local FalkorDB
# client merely to import the graph package.
for _module in ("falkordb", "psycopg", "psycopg.types", "psycopg.types.json"):
    sys.modules.setdefault(_module, MagicMock())

from aryx.api.graph_api import create_app


def _client(monkeypatch) -> tuple[TestClient, MagicMock]:
    reader = MagicMock()
    reader.run_readonly.return_value = (["name", "count"], [["Steel", 3]])
    monkeypatch.setattr("aryx.api.graph_api.GraphReader", lambda *_: reader)
    app = create_app()
    return TestClient(app), reader


def _post(client: TestClient, body: dict, key: str | None = "valid-key"):
    headers = {"x-aryx-api-key": key} if key else {}
    with patch("aryx.api.security._verify_key", return_value=bool(key)):
        return client.post("/graph/cypher", json=body, headers=headers)


def test_cypher_accepts_a_bearer_token(monkeypatch) -> None:
    client, _ = _client(monkeypatch)
    with patch("aryx.api.security._verify_key", return_value=True):
        response = client.post(
            "/graph/cypher",
            json={"workspace_id": 51, "query": "MATCH (e:Entity) RETURN e.id"},
            headers={"Authorization": "Bearer valid-token"},
        )

    assert response.status_code == 200


def test_cypher_requires_an_api_key(monkeypatch) -> None:
    client, _ = _client(monkeypatch)

    response = _post(client, {
        "workspace_id": 51,
        "query": "MATCH (e:Entity) RETURN e.id",
    }, key=None)

    assert response.status_code == 401


def test_cypher_requires_a_workspace_id(monkeypatch) -> None:
    client, _ = _client(monkeypatch)

    response = _post(client, {"query": "MATCH (e:Entity) RETURN e.id"})

    assert response.status_code == 422


def test_cypher_forwards_string_and_list_parameters(monkeypatch) -> None:
    client, reader = _client(monkeypatch)

    response = _post(client, {
        "workspace_id": 51,
        "query": "MATCH (e:Entity) WHERE e.type IN $types RETURN e.name AS name, 1 AS count",
        "params": {"types": ["Material", "NoBid"]},
        "limit": 10,
    })

    assert response.status_code == 200
    assert response.json()["rows"] == [{"name": "Steel", "count": 3}]
    query, params, timeout_ms = reader.run_readonly.call_args.args
    assert query.endswith("LIMIT 10")
    assert params == {"types": ["Material", "NoBid"]}
    assert timeout_ms is None


def test_cypher_rejects_an_unapproved_procedure(monkeypatch) -> None:
    client, reader = _client(monkeypatch)

    response = _post(client, {
        "workspace_id": 51,
        "query": "CALL db.idx.fulltext.createNodeIndex('idx', ['Entity'], ['name'])",
    })

    assert response.status_code == 400
    assert "not on the read-only allowlist" in response.json()["detail"]
    reader.run_readonly.assert_not_called()


def test_cypher_injects_a_bounded_limit_and_reports_truncation(monkeypatch) -> None:
    client, reader = _client(monkeypatch)
    reader.run_readonly.return_value = (["id"], [[1], [2], [3]])

    response = _post(client, {
        "workspace_id": 51,
        "query": "MATCH (e:Entity) RETURN e.id AS id",
        "limit": 2,
    })

    assert response.status_code == 200
    assert response.json()["limited"] is True
    assert response.json()["rows"] == [{"id": 1}, {"id": 2}]
    assert reader.run_readonly.call_args.args[0].endswith("LIMIT 2")


def test_cypher_allows_read_only_fulltext_procedures(monkeypatch) -> None:
    client, _ = _client(monkeypatch)

    response = _post(client, {
        "workspace_id": 51,
        "query": "CALL db.idx.fulltext.queryNodes('Entity', 'steel') YIELD node RETURN node",
    })

    assert response.status_code == 200
