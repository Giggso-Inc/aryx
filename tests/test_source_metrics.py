"""Pure source-catalog paging and metric shaping tests."""
from __future__ import annotations

from collections import Counter

from aryx.source_metrics import (
    apply_source_metrics,
    page_source_catalog,
    source_references,
)


def _source(index: int, *, kind: str = "csv") -> dict:
    return {
        "source_key": f"{kind}:source-{index:04d}",
        "name": f"{kind}.source-{index:04d}",
        "display_kind": "Structured CSV",
        "kind": kind,
        "record_count": index,
        "isXmlParent": False,
        "generatedAssetCount": 0,
        "actions": {"view": True, "download": True, "delete": True},
    }


def test_page_source_catalog_thousand_sources_returns_bounded_page() -> None:
    result = page_source_catalog([_source(i) for i in range(1001)], page=2, page_size=50)

    assert len(result["items"]) == 50
    assert result["total"] == 1001
    assert result["page"] == 2


def test_page_source_catalog_query_and_category_preserve_order() -> None:
    rows = [_source(1), _source(2, kind="rest"), _source(3)]

    result = page_source_catalog(rows, query="source-000", category="api")

    assert [row["source_key"] for row in result["items"]] == ["rest:source-0002"]


def test_apply_source_metrics_uses_distinct_entity_type_counts() -> None:
    rows = [_source(1)]
    stats = {"csv:source-0001": [("Customer", 12), ("Order", 4)]}
    edge_stats = {"csv:source-0001": 7}

    enriched = apply_source_metrics(rows, stats, edge_stats)

    assert enriched[0]["total_entities"] == 16
    assert enriched[0]["entity_type_count"] == 2
    assert enriched[0]["node_count"] == 16
    assert enriched[0]["edge_count"] == 7


def test_source_references_grouped_assets_excludes_deleted_assets() -> None:
    datasources = [{
        "id": 42,
        "kind": "xlsx",
        "config": {"source_catalog": {"xlsx": {"generated_assets": [
            {"dataset": "Customers"},
            {"dataset": "Orders", "deleted": True},
        ]}}},
    }]

    refs = source_references("xlsx:42", datasources, Counter())

    assert refs == [("csv", "Customers")]


def test_source_references_generic_key_preserves_special_dataset_text() -> None:
    refs = source_references("rest:orders/2026 west", [], Counter())

    assert refs == [("rest", "orders/2026 west")]
