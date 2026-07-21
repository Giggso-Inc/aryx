"""Universal source detail and paginated catalog API tests."""
from __future__ import annotations

from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from aryx.api.data_api import data_router
from tests.test_data_sources_api import _FakeDatasourceStore, _FakeEntityStore


class _FakeMetricsStore:
    def __init__(
        self,
        source_count: int = 1,
        source_counts: dict[tuple[str, str], int] | None = None,
    ) -> None:
        self.source_count = source_count
        self.source_counts = source_counts

    def source_record_counts(self) -> dict[tuple[str, str], int]:
        if self.source_counts is not None:
            return self.source_counts
        return {("csv", f"source-{i:04d}"): i + 1 for i in range(self.source_count)}

    def source_entity_type_counts(
        self, source_map: list[tuple[str, str, str]],
    ) -> dict[str, list[tuple[str, int]]]:
        return {
            key: [("Customer", 12), ("Order", 4)]
            for key, _system, _dataset in source_map
        }

    def source_edge_counts(
        self, source_map: list[tuple[str, str, str]],
    ) -> dict[str, int]:
        return {key: 7 for key, _system, _dataset in source_map}

    def source_records_page(
        self, system: str, dataset: str, *, limit: int, offset: int,
    ) -> tuple[int, list[dict]]:
        rows = [{"id": i, "dataset": dataset} for i in range(offset, offset + limit)]
        return 100, rows

    def close(self) -> None:
        return None


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(data_router())
    return TestClient(app, raise_server_exceptions=False)


def _patches(metrics: _FakeMetricsStore):
    return (
        patch("aryx.api.data_api.DatasourceStore", return_value=_FakeDatasourceStore([])),
        patch("aryx.api.data_api._store", return_value=_FakeEntityStore([])),
        patch("aryx.api.data_api._metric_reader", return_value=metrics),
    )


def test_sources_page_thousand_sources_returns_first_fifty() -> None:
    patches = _patches(_FakeMetricsStore(1001))
    with patches[0], patches[1], patches[2]:
        response = _client().get("/data/sources/page?workspace_id=1&page=1&page_size=100")

    assert response.status_code == 200
    assert response.json()["total"] == 1001
    assert len(response.json()["items"]) == 50
    assert response.json()["page_size"] == 50
    assert response.json()["items"][0]["node_count"] == 16
    assert response.json()["items"][0]["edge_count"] == 7


def test_generic_source_detail_contains_selected_source_entity_summary() -> None:
    patches = _patches(_FakeMetricsStore())
    with patches[0], patches[1], patches[2]:
        response = _client().get("/data/sources/csv:source-0000?workspace_id=1")

    assert response.status_code == 200
    assert response.json()["detail_kind"] == "preview"
    assert response.json()["entity_summary"]["total_entities"] == 16
    assert response.json()["entity_summary"]["node_count"] == 16
    assert response.json()["entity_summary"]["edge_count"] == 7


def test_source_entity_types_endpoint_is_paginated() -> None:
    metrics = _FakeMetricsStore()
    metrics.source_entity_type_counts = lambda _mapping: {
        "csv:source-0000": [(f"Type{i:02d}", 60 - i) for i in range(60)]
    }
    patches = _patches(metrics)
    with patches[0], patches[1], patches[2]:
        response = _client().get(
            "/data/sources/csv:source-0000/entity-types?workspace_id=1&page=1&page_size=100",
        )

    assert response.status_code == 200
    assert response.json()["total"] == 60
    assert len(response.json()["items"]) == 50


def test_source_records_endpoint_bounds_preview_rows() -> None:
    patches = _patches(_FakeMetricsStore())
    with patches[0], patches[1], patches[2]:
        response = _client().get(
            "/data/sources/csv:source-0000/records?workspace_id=1&page=2&page_size=100",
        )

    assert response.status_code == 200
    assert response.json()["rows"][0]["id"] == 25
    assert len(response.json()["rows"]) == 25


def test_source_detail_accepts_encoded_slash_and_space_in_key() -> None:
    metrics = _FakeMetricsStore(source_counts={("rest", "orders/2026 west"): 2})
    patches = _patches(metrics)
    with patches[0], patches[1], patches[2]:
        response = _client().get(
            "/data/sources/rest:orders%2F2026%20west?workspace_id=1",
        )

    assert response.status_code == 200
    assert response.json()["source_key"] == "rest:orders/2026 west"
