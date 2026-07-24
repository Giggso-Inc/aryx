"""Source metric store query-boundary regression tests."""
from __future__ import annotations

from typing import Any

from aryx.queries import load
from aryx.store.source_metrics_store import SourceMetricsStore


def test_source_type_query_deduplicates_entities_across_grouped_datasets() -> None:
    query = load("select_source_entity_type_counts")

    assert "SELECT DISTINCT mapped.source_key, entity.id" in query
    assert "landed.workspace_id = %(workspace_id)s" in query
    assert "entity.workspace_id = member.workspace_id" in query


def test_source_edge_query_counts_distinct_incident_relationships() -> None:
    query = load("select_source_edge_counts")

    assert "SELECT DISTINCT" in query
    assert "relationship.source_entity_id = entity_links.id" in query
    assert "relationship.target_entity_id = entity_links.id" in query
    assert "relationship.workspace_id = %(workspace_id)s" in query


def test_source_map_deduplicates_references_and_scopes_workspace() -> None:
    store = SourceMetricsStore.__new__(SourceMetricsStore)
    store._ws = 41
    captured: dict[str, Any] = {}

    def fake_all(query: str, params: dict[str, Any]) -> list[tuple]:
        captured.update({"query": query, "params": params})
        return [("xlsx:9", "Customer", 3)]

    store._all = fake_all  # type: ignore[method-assign]
    result = store.source_entity_type_counts([
        ("xlsx:9", "csv", "Customers"),
        ("xlsx:9", "csv", "Customers"),
        ("xlsx:9", "csv", "Orders"),
    ])

    payload = captured["params"]["source_map"].obj
    assert captured["params"]["workspace_id"] == 41
    assert len(payload) == 2
    assert result == {"xlsx:9": [("Customer", 3)]}


def test_source_edge_counts_deduplicates_references_and_scopes_workspace() -> None:
    store = SourceMetricsStore.__new__(SourceMetricsStore)
    store._ws = 41
    captured: dict[str, Any] = {}

    def fake_all(query: str, params: dict[str, Any]) -> list[tuple]:
        captured.update({"query": query, "params": params})
        return [("xlsx:9", 5)]

    store._all = fake_all  # type: ignore[method-assign]
    result = store.source_edge_counts([
        ("xlsx:9", "csv", "Customers"),
        ("xlsx:9", "csv", "Customers"),
        ("xlsx:9", "csv", "Orders"),
    ])

    payload = captured["params"]["source_map"].obj
    assert captured["params"]["workspace_id"] == 41
    assert len(payload) == 2
    assert result == {"xlsx:9": 5}
