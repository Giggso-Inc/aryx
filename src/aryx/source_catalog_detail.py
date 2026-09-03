"""Read-side catalog/detail builders — the Data tab's list + drill-down views.

Split out of `source_catalog.py` (Raven Style Compliance Plan, Phase 2a,
2026-09-03).
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from aryx.source_catalog_meta import (
    _active_assets,
    _asset_rows,
    _display_kind,
    _generic_meta,
    _legacy_groups,
    _preview_payload_rows,
    _preview_rows,
    _source_counts,
    _xlsx_meta,
    _xml_meta,
    source_actions,
)
from aryx.source_catalog_upsert import (
    _CATALOG_KEY,
    _XML_KEY,
    find_legacy_xml_row,
    legacy_xml_catalog_config,
)


def build_source_catalog(
    datasources: list[dict[str, Any]],
    provenance: list[tuple[int, str, str, str]] | tuple[tuple[int, str, str, str], ...],
) -> list[dict[str, Any]]:
    """Build the catalog from legacy row-level provenance input."""
    return build_source_catalog_from_counts(datasources, _source_counts(provenance))


def build_source_catalog_from_counts(
    datasources: list[dict[str, Any]],
    counts: Counter[tuple[str, str]],
) -> list[dict[str, Any]]:
    """Build the catalog from bounded database-side source counts."""
    rows: list[dict[str, Any]] = []
    hidden_datasets: set[str] = set()
    covered_keys: set[tuple[str, str]] = set()
    generic_visibility: dict[tuple[str, str], dict[str, bool]] = {}

    for row in datasources:
        generic_meta = _generic_meta(row)
        if generic_meta is not None:
            key = (
                str(generic_meta.get("source_system") or ""),
                str(generic_meta.get("source_dataset") or ""),
            )
            state = generic_visibility.setdefault(key, {"deleted": False, "active": False})
            if "is_active" in generic_meta:
                if generic_meta.get("is_active"):
                    state["active"] = True
                else:
                    state["deleted"] = True
            else:
                # Old generic tombstones did not follow Accsell's active-row
                # lifecycle, so they should not strand live re-uploaded data.
                state["active"] = True
            continue
        xml_meta = _xml_meta(row)
        xlsx_meta = _xlsx_meta(row)
        if xml_meta is None and xlsx_meta is None:
            rows.append({
                "source_key": f"ds:{row['id']}",
                "name": row.get("name") or f"datasource:{row['id']}",
                "display_kind": _display_kind(str(row.get("kind") or "datasource"), row.get("name") or ""),
                "kind": row.get("kind") or "datasource",
                "ready": bool(row.get("ready", True)),
                "record_count": 0,
                "isXmlParent": False,
                "generatedAssetCount": 0,
                "actions": source_actions(True, False, False),
            })
            continue

        # Same "parent workbook/document -> generated per-dataset assets"
        # grouping for both source_key prefixes — only the meta lookup,
        # source_key prefix, and display label differ.
        meta, source_prefix, display_kind, display_kind_key = (
            (xml_meta, "xml", "XML File", "xml")
            if xml_meta is not None
            else (xlsx_meta, "xlsx", "Excel Workbook", "xlsx")
        )
        active_assets = _active_assets(meta)
        all_assets = _asset_rows(meta)
        hidden_datasets.update(
            asset.get("dataset", "")
            for asset in all_assets
            if asset.get("dataset")
        )
        if meta.get("deleted"):
            continue
        rows.append({
            "source_key": f"{source_prefix}:{row['id']}",
            "name": meta.get("source_filename") or row.get("name") or f"{source_prefix}:{row['id']}",
            "display_kind": display_kind,
            "kind": display_kind_key,
            "ready": True,
            "record_count": sum(
                counts.get(("csv", asset.get("dataset", "")), 0)
                for asset in active_assets
            ),
            "isXmlParent": True,
            "generatedAssetCount": len(active_assets),
            "actions": source_actions(
                True,
                bool(meta.get("content_b64")) or bool(meta.get("legacy_prefix")) or bool(active_assets),
                True,
            ),
        })
        for asset in active_assets:
            dataset = asset.get("dataset")
            if dataset:
                covered_keys.add(("csv", dataset))

    hidden_generic_keys = {
        key for key, state in generic_visibility.items()
        if state["deleted"] and not state["active"]
    }

    legacy_groups = _legacy_groups(counts, hidden_datasets, {dataset for _, dataset in covered_keys})
    for prefix, datasets in legacy_groups.items():
        rows.append({
            "source_key": f"legacy-xml:{prefix}",
            "name": f"{prefix}.xml",
            "display_kind": "XML File",
            "kind": "xml",
            "ready": True,
            "record_count": sum(counts[("csv", dataset)] for dataset in datasets),
            "isXmlParent": True,
            "generatedAssetCount": len(datasets),
            "actions": source_actions(True, True, True),
        })
        covered_keys.update({("csv", dataset) for dataset in datasets})

    for (system, dataset), count in counts.most_common():
        if (
            dataset in hidden_datasets
            or (system, dataset) in covered_keys
            or (system, dataset) in hidden_generic_keys
        ):
            continue
        rows.append({
            "source_key": f"{system}:{dataset}",
            "name": f"{system}.{dataset}",
            "display_kind": _display_kind(system, dataset),
            "kind": system,
            "ready": True,
            "record_count": count,
            "isXmlParent": False,
            "generatedAssetCount": 0,
            "actions": source_actions(True, True, True),
        })
    return rows


def _build_meta_source_detail(
    source_key: str,
    datasources: list[dict[str, Any]],
    counts: Counter[tuple[str, str]],
    dataset_payloads: dict[str, list[dict[str, Any]]],
    meta_fn: Any,
    primary_label: str,
) -> dict[str, Any] | None:
    """Shared body for the "one parent row -> N generated CSV assets" detail
    view — used by both xml: and xlsx: source keys (see meta_fn)."""
    try:
        datasource_id = int(source_key.split(":", 1)[1])
    except ValueError:
        return None
    row = next((item for item in datasources if int(item["id"]) == datasource_id), None)
    if row is None:
        return None
    meta = meta_fn(row) or {}
    if meta.get("deleted"):
        return None
    assets = []
    for asset in _active_assets(meta):
        dataset = asset.get("dataset", "")
        preview_rows = _preview_payload_rows(dataset_payloads.get(dataset))
        if not preview_rows:
            preview_rows = _preview_rows(asset.get("content_b64"))
        can_download = (
            bool(asset.get("content_b64"))
            or bool(dataset_payloads.get(dataset))
            or counts.get(("csv", dataset), 0) > 0
        )
        assets.append({
            "asset_key": asset.get("asset_key") or asset.get("filename") or dataset,
            "filename": asset.get("filename") or dataset,
            "dataset": dataset,
            "ontology_type": asset.get("ontology_type") or dataset,
            "status": "Ready",
            "record_count": counts.get(("csv", dataset), 0),
            "preview_rows": preview_rows,
            "actions": source_actions(True, can_download, True),
        })
    return {
        "source_key": source_key,
        "name": meta.get("source_filename") or row.get("name"),
        "status": "Ready",
        "generatedAssetCount": len(assets),
        "record_count": sum(asset["record_count"] for asset in assets),
        "primary": {
            "label": primary_label,
            "status": "Active",
            "actions": source_actions(
                True,
                bool(meta.get("content_b64")) or bool(meta.get("legacy_prefix")) or bool(assets),
                True,
            ),
        },
        "assets": assets,
    }


def build_source_detail(
    source_key: str,
    datasources: list[dict[str, Any]],
    provenance: list[tuple[int, str, str, str]] | tuple[tuple[int, str, str, str], ...],
    dataset_payloads: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any] | None:
    """Build grouped detail from legacy row-level provenance input."""
    return build_source_detail_from_counts(
        source_key,
        datasources,
        _source_counts(provenance),
        dataset_payloads=dataset_payloads,
    )


def build_source_detail_from_counts(
    source_key: str,
    datasources: list[dict[str, Any]],
    counts: Counter[tuple[str, str]],
    dataset_payloads: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any] | None:
    """Build grouped XML/XLSX detail from bounded source counts."""
    dataset_payloads = dataset_payloads or {}
    if source_key.startswith("xml:"):
        return _build_meta_source_detail(
            source_key, datasources, counts, dataset_payloads,
            _xml_meta, "XML / Preserved Upload",
        )

    if source_key.startswith("xlsx:"):
        return _build_meta_source_detail(
            source_key, datasources, counts, dataset_payloads,
            _xlsx_meta, "Excel Workbook / Preserved Upload",
        )

    if source_key.startswith("legacy-xml:"):
        prefix = source_key.split(":", 1)[1]
        legacy_row = find_legacy_xml_row(datasources, prefix)
        if legacy_row is not None:
            meta = _xml_meta(legacy_row) or {}
            if meta.get("deleted"):
                return None
            raw_assets = _active_assets(meta)
        else:
            datasets = _legacy_groups(counts, set(), set()).get(prefix)
            if not datasets:
                return None
            raw_assets = _asset_rows(legacy_xml_catalog_config(prefix, datasets)[_CATALOG_KEY][_XML_KEY])

        assets = []
        for asset in raw_assets:
            dataset = asset.get("dataset", "")
            assets.append({
                "asset_key": asset.get("asset_key") or dataset,
                "filename": asset.get("filename") or f"{dataset}.csv",
                "dataset": dataset,
                "ontology_type": asset.get("ontology_type") or dataset.rsplit("_", 1)[-1],
                "status": "Ready",
                "record_count": counts.get(("csv", dataset), 0),
                "preview_rows": _preview_payload_rows(dataset_payloads.get(dataset)),
                "actions": source_actions(True, True, True),
            })
        return {
            "source_key": source_key,
            "name": f"{prefix}.xml",
            "status": "Ready",
            "generatedAssetCount": len(assets),
            "record_count": sum(asset["record_count"] for asset in assets),
            "primary": {
                "label": "XML / Preserved Lineage",
                "status": "Active",
                "actions": source_actions(True, True, True),
            },
            "assets": assets,
        }

    return None
