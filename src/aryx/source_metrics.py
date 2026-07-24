"""Bounded source-catalog paging and source-reference shaping."""
from __future__ import annotations

from collections import Counter
from typing import Any, Literal

SourceCategory = Literal["all", "database", "documents", "api"]
SourceCounts = Counter[tuple[str, str]]
SourceStats = dict[str, list[tuple[str, int]]]
SourceEdgeStats = dict[str, int]

_DATABASE_KINDS = {"postgresql", "postgres", "mysql", "mariadb", "oracle", "sqlite", "csv"}


def page_source_catalog(
    rows: list[dict[str, Any]], *, query: str = "", category: SourceCategory = "all",
    page: int = 1, page_size: int = 50,
) -> dict[str, Any]:
    """Filter and slice an already aggregated source catalog."""
    needle = query.strip().lower()
    filtered = [row for row in rows if _matches(row, needle, category)]
    safe_page = max(1, int(page))
    safe_size = max(1, min(int(page_size), 100))
    start = (safe_page - 1) * safe_size
    return {
        "items": filtered[start:start + safe_size],
        "total": len(filtered),
        "page": safe_page,
        "page_size": safe_size,
    }


def apply_source_metrics(
    rows: list[dict[str, Any]],
    stats: SourceStats,
    edge_stats: SourceEdgeStats | None = None,
) -> list[dict[str, Any]]:
    """Attach node, edge, entity, and entity-type counts to catalog rows."""
    enriched: list[dict[str, Any]] = []
    edge_stats = edge_stats or {}
    for row in rows:
        type_counts = stats.get(str(row["source_key"]), [])
        total_entities = sum(count for _name, count in type_counts)
        enriched.append({
            **row,
            "total_entities": total_entities,
            "entity_type_count": len(type_counts),
            "node_count": total_entities,
            "edge_count": edge_stats.get(str(row["source_key"]), 0),
        })
    return enriched


def source_references(
    source_key: str, datasources: list[dict[str, Any]], counts: SourceCounts,
) -> list[tuple[str, str]]:
    """Resolve a logical catalog row to its physical provenance datasets."""
    prefix, _, suffix = source_key.partition(":")
    if prefix in {"xml", "xlsx"}:
        return _parent_references(prefix, suffix, datasources)
    if prefix == "legacy-xml":
        hidden = _parent_datasets(datasources)
        return sorted(
            (system, dataset) for system, dataset in counts
            if system == "csv" and dataset.startswith(f"{suffix}_") and dataset not in hidden
        )
    if prefix == "ds" or not prefix or not suffix:
        return []
    return [(prefix, suffix)]


def mapped_references(
    rows: list[dict[str, Any]], datasources: list[dict[str, Any]], counts: SourceCounts,
) -> list[tuple[str, str, str]]:
    """Flatten logical-to-physical source mappings for one bounded catalog page."""
    return [
        (str(row["source_key"]), system, dataset)
        for row in rows
        for system, dataset in source_references(str(row["source_key"]), datasources, counts)
    ]


def _matches(row: dict[str, Any], needle: str, category: SourceCategory) -> bool:
    """Return whether one catalog row satisfies the normalized filters."""
    kind = str(row.get("kind") or "").lower()
    display_kind = str(row.get("display_kind") or "").lower()
    if category == "database" and kind not in _DATABASE_KINDS:
        return False
    if category == "documents" and kind not in {"xml", "xlsx"} and display_kind != "document":
        return False
    if category == "api" and kind not in {"rest", "api"}:
        return False
    haystack = " ".join(str(row.get(key) or "") for key in ("name", "kind", "display_kind", "source_key"))
    return needle in haystack.lower()


def _parent_references(prefix: str, suffix: str, datasources: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """Return active physical assets for an XML or XLSX parent row."""
    try:
        datasource_id = int(suffix)
    except ValueError:
        return []
    row = next((item for item in datasources if int(item.get("id", -1)) == datasource_id), None)
    meta = ((row or {}).get("config") or {}).get("source_catalog", {}).get(prefix, {})
    return [
        ("csv", str(asset["dataset"])) for asset in meta.get("generated_assets", [])
        if isinstance(asset, dict) and asset.get("dataset") and not asset.get("deleted")
    ]


def _parent_datasets(datasources: list[dict[str, Any]]) -> set[str]:
    """Return datasets owned by persisted grouped parent sources."""
    datasets: set[str] = set()
    for row in datasources:
        catalog = ((row.get("config") or {}).get("source_catalog") or {})
        for key in ("xml", "xlsx"):
            for asset in (catalog.get(key) or {}).get("generated_assets", []):
                if isinstance(asset, dict) and asset.get("dataset"):
                    datasets.add(str(asset["dataset"]))
    return datasets
