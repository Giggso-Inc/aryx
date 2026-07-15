"""XML-aware source catalog helpers for the Data tab."""
from __future__ import annotations

import base64
import csv
import io
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import UTC, datetime
from typing import Any

_CATALOG_KEY = "source_catalog"
_XML_KEY = "xml"
_XLSX_KEY = "xlsx"
_GENERIC_KEY = "generic"


def _source_counts(
    provenance: list[tuple[int, str, str, str]] | tuple[tuple[int, str, str, str], ...],
) -> Counter[tuple[str, str]]:
    counts: Counter[tuple[str, str]] = Counter()
    for _, system, dataset, _ in provenance:
        counts[(system, dataset)] += 1
    return counts


def _xml_meta(row: dict[str, Any]) -> dict[str, Any] | None:
    config = row.get("config") or {}
    meta = config.get(_CATALOG_KEY, {}).get(_XML_KEY)
    if isinstance(meta, dict):
        return meta
    if row.get("kind") == "xml":
        return {}
    return None


def _xlsx_meta(row: dict[str, Any]) -> dict[str, Any] | None:
    config = row.get("config") or {}
    meta = config.get(_CATALOG_KEY, {}).get(_XLSX_KEY)
    if isinstance(meta, dict):
        return meta
    if row.get("kind") == "xlsx":
        return {}
    return None


def _generic_meta(row: dict[str, Any]) -> dict[str, Any] | None:
    config = row.get("config") or {}
    meta = config.get(_CATALOG_KEY, {}).get(_GENERIC_KEY)
    if isinstance(meta, dict):
        return meta
    return None


def _asset_rows(meta: dict[str, Any]) -> list[dict[str, Any]]:
    assets = meta.get("generated_assets") or []
    if not isinstance(assets, list):
        return []
    return [asset for asset in assets if isinstance(asset, dict)]


def _active_assets(meta: dict[str, Any]) -> list[dict[str, Any]]:
    return [asset for asset in _asset_rows(meta) if not asset.get("deleted")]


def _legacy_groups(
    counts: Counter[tuple[str, str]],
    hidden_datasets: set[str],
    covered_datasets: set[str],
) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for system, dataset in counts:
        if system != "csv" or dataset in hidden_datasets or dataset in covered_datasets:
            continue
        if "_" not in dataset:
            continue
        prefix, _suffix = dataset.rsplit("_", 1)
        if not prefix:
            continue
        groups.setdefault(prefix, []).append(dataset)
    return {
        prefix: sorted(datasets)
        for prefix, datasets in groups.items()
        if len(datasets) >= 2
    }


def _preview_rows(content_b64: str | None, limit: int = 5) -> list[dict[str, str]]:
    if not content_b64:
        return []
    try:
        raw = base64.b64decode(content_b64)
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8", "ignore")))
        rows: list[dict[str, str]] = []
        for idx, row in enumerate(reader):
            rows.append({str(k): "" if v is None else str(v) for k, v in row.items()})
            if idx + 1 >= limit:
                break
        return rows
    except Exception:  # noqa: BLE001
        return []


def _preview_payload_rows(
    payload_rows: list[dict[str, Any]] | None,
    limit: int = 5,
) -> list[dict[str, str]]:
    if not payload_rows:
        return []
    rows: list[dict[str, str]] = []
    for payload in payload_rows[:limit]:
        rows.append({
            str(key): "" if value is None else str(value)
            for key, value in (payload or {}).items()
        })
    return rows


def _csv_bytes_from_payload_rows(payload_rows: list[dict[str, Any]] | None) -> bytes | None:
    if not payload_rows:
        return None
    headers: list[str] = []
    for row in payload_rows:
        for key in (row or {}).keys():
            text_key = str(key)
            if text_key not in headers:
                headers.append(text_key)
    if not headers:
        return None
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=headers)
    writer.writeheader()
    for row in payload_rows:
        writer.writerow({
            header: "" if row.get(header) is None else str(row.get(header))
            for header in headers
        })
    return buffer.getvalue().encode("utf-8")


def source_actions(view: bool, download: bool, delete: bool) -> dict[str, bool]:
    return {"view": view, "download": download, "delete": delete}


def generic_catalog_config(
    source_system: str,
    source_dataset: str,
    *,
    is_active: bool,
) -> dict[str, Any]:
    deleted_at = datetime.now(UTC).isoformat() if not is_active else None
    return {
        _CATALOG_KEY: {
            _GENERIC_KEY: {
                "source_system": source_system,
                "source_dataset": source_dataset,
                "is_active": is_active,
                "deleted": not is_active,
                "deleted_at": deleted_at,
            },
        },
    }


def xml_catalog_config(
    source_filename: str,
    xml_bytes: bytes,
    assets: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        _CATALOG_KEY: {
            _XML_KEY: {
                "source_filename": source_filename,
                "content_type": "application/xml",
                "content_b64": base64.b64encode(xml_bytes).decode("ascii"),
                "generated_assets": assets,
                "deleted": False,
            },
        },
    }


def legacy_xml_catalog_config(prefix: str, datasets: list[str]) -> dict[str, Any]:
    assets = []
    for dataset in datasets:
        assets.append({
            "asset_key": dataset,
            "filename": f"{dataset}.csv",
            "dataset": dataset,
            "ontology_type": dataset.rsplit("_", 1)[-1],
            "deleted": False,
        })
    return {
        _CATALOG_KEY: {
            _XML_KEY: {
                "source_filename": f"{prefix}.xml",
                "content_type": "application/xml",
                "legacy_prefix": prefix,
                "generated_assets": assets,
                "deleted": False,
            },
        },
    }


def xml_asset_record(
    *,
    filename: str,
    dataset: str,
    ontology_type: str,
    content_bytes: bytes,
) -> dict[str, Any]:
    return {
        "asset_key": filename,
        "filename": filename,
        "dataset": dataset,
        "ontology_type": ontology_type,
        "content_type": "text/csv",
        "content_b64": base64.b64encode(content_bytes).decode("ascii"),
        "deleted": False,
    }


def upsert_xml_catalog_entry(
    store: Any,
    *,
    workspace_id: int,
    source_filename: str,
    xml_bytes: bytes,
    assets: list[dict[str, Any]],
) -> dict[str, Any]:
    rows = store.list(workspace_id)
    existing = next(
        (
            row for row in rows
            if row.get("name") == source_filename and _xml_meta(row) is not None
        ),
        None,
    )
    config = xml_catalog_config(source_filename, xml_bytes, assets)
    if existing:
        return store.update(
            int(existing["id"]),
            name=source_filename,
            kind="xml",
            config=config,
            secret=None,
        )
    return store.add(
        workspace_id,
        source_filename,
        "xml",
        config,
        "",
    )


def xlsx_catalog_config(
    source_filename: str,
    xlsx_bytes: bytes,
    assets: list[dict[str, Any]],
) -> dict[str, Any]:
    """Same shape as xml_catalog_config — one workbook, N generated per-sheet
    CSV assets. This is what "maintains the association with the parent
    workbook" for a multi-sheet Excel upload: the original .xlsx bytes plus
    every sheet-derived dataset are held on one datasource_store row, so a
    later query can recover every dataset that came from one upload."""
    return {
        _CATALOG_KEY: {
            _XLSX_KEY: {
                "source_filename": source_filename,
                "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "content_b64": base64.b64encode(xlsx_bytes).decode("ascii"),
                "generated_assets": assets,
                "deleted": False,
            },
        },
    }


def xlsx_asset_record(
    *,
    filename: str,
    dataset: str,
    ontology_type: str,
    content_bytes: bytes,
) -> dict[str, Any]:
    return {
        "asset_key": filename,
        "filename": filename,
        "dataset": dataset,
        "ontology_type": ontology_type,
        "content_type": "text/csv",
        "content_b64": base64.b64encode(content_bytes).decode("ascii"),
        "deleted": False,
    }


def upsert_xlsx_catalog_entry(
    store: Any,
    *,
    workspace_id: int,
    source_filename: str,
    xlsx_bytes: bytes,
    assets: list[dict[str, Any]],
) -> dict[str, Any]:
    rows = store.list(workspace_id)
    existing = next(
        (
            row for row in rows
            if row.get("name") == source_filename
            and (row.get("config") or {}).get(_CATALOG_KEY, {}).get(_XLSX_KEY) is not None
        ),
        None,
    )
    config = xlsx_catalog_config(source_filename, xlsx_bytes, assets)
    if existing:
        return store.update(
            int(existing["id"]),
            name=source_filename,
            kind="xlsx",
            config=config,
            secret=None,
        )
    return store.add(
        workspace_id,
        source_filename,
        "xlsx",
        config,
        "",
    )


def find_legacy_xml_row(datasources: list[dict[str, Any]], prefix: str) -> dict[str, Any] | None:
    expected_name = f"{prefix}.xml"
    for row in datasources:
        meta = _xml_meta(row)
        if meta is None:
            continue
        if meta.get("legacy_prefix") == prefix:
            return row
        if (
            not meta.get("content_b64")
            and bool(_asset_rows(meta))
            and (meta.get("source_filename") or row.get("name")) == expected_name
        ):
            return row
    return None


def find_generic_source_row(
    datasources: list[dict[str, Any]],
    source_system: str,
    source_dataset: str,
) -> dict[str, Any] | None:
    for row in datasources:
        meta = _generic_meta(row)
        if meta is None:
            continue
        if (
            meta.get("source_system") == source_system
            and meta.get("source_dataset") == source_dataset
        ):
            return row
    return None


def legacy_xml_row(
    prefix: str,
    datasets: list[str],
    *,
    datasource_id: int = 0,
    workspace_id: int = 0,
) -> dict[str, Any]:
    return {
        "id": datasource_id,
        "workspace_id": workspace_id,
        "name": f"{prefix}.xml",
        "kind": "xml",
        "config": legacy_xml_catalog_config(prefix, datasets),
        "secret_mask": "",
        "created_at": None,
    }


def upsert_legacy_xml_catalog_entry(
    store: Any,
    *,
    workspace_id: int,
    prefix: str,
    datasets: list[str],
) -> dict[str, Any]:
    rows = store.list(workspace_id)
    existing = find_legacy_xml_row(rows, prefix)
    config = legacy_xml_catalog_config(prefix, datasets)
    if existing:
        return store.update(
            int(existing["id"]),
            name=f"{prefix}.xml",
            kind="xml",
            config=config,
            secret=None,
        )
    return store.add(
        workspace_id,
        f"{prefix}.xml",
        "xml",
        config,
        "",
    )


def upsert_generic_source_entry(
    store: Any,
    *,
    workspace_id: int,
    source_system: str,
    source_dataset: str,
) -> dict[str, Any]:
    rows = store.list(workspace_id)
    existing = find_generic_source_row(rows, source_system, source_dataset)
    config = generic_catalog_config(source_system, source_dataset, is_active=False)
    name = f"{source_system}.{source_dataset}"
    if existing:
        return store.update(
            int(existing["id"]),
            name=name,
            kind="source_catalog",
            config=config,
            secret=None,
        )
    return store.add(
        workspace_id,
        name,
        "source_catalog",
        config,
        "",
    )


def restore_generic_source_entry(
    store: Any,
    *,
    workspace_id: int,
    source_system: str,
    source_dataset: str,
) -> dict[str, Any] | None:
    rows = store.list(workspace_id)
    existing = find_generic_source_row(rows, source_system, source_dataset)
    if existing is None:
        return None
    return store.update(
        int(existing["id"]),
        name=f"{source_system}.{source_dataset}",
        kind="source_catalog",
        config=generic_catalog_config(source_system, source_dataset, is_active=True),
        secret=None,
    )


def build_source_catalog(
    datasources: list[dict[str, Any]],
    provenance: list[tuple[int, str, str, str]] | tuple[tuple[int, str, str, str], ...],
) -> list[dict[str, Any]]:
    counts = _source_counts(provenance)
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
                "actions": source_actions(False, False, False),
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
        preview_rows = _preview_rows(asset.get("content_b64"))
        if not preview_rows:
            preview_rows = _preview_payload_rows(dataset_payloads.get(dataset))
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
    counts = _source_counts(provenance)
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


def mark_xml_source_deleted(row: dict[str, Any]) -> dict[str, Any]:
    config = dict(row.get("config") or {})
    catalog = dict(config.get(_CATALOG_KEY) or {})
    meta = dict(catalog.get(_XML_KEY) or {})
    meta["deleted"] = True
    for asset in _asset_rows(meta):
        asset["deleted"] = True
    catalog[_XML_KEY] = meta
    config[_CATALOG_KEY] = catalog
    return config


def mark_xml_asset_deleted(row: dict[str, Any], asset_key: str) -> dict[str, Any]:
    config = dict(row.get("config") or {})
    catalog = dict(config.get(_CATALOG_KEY) or {})
    meta = dict(catalog.get(_XML_KEY) or {})
    assets = []
    for asset in _asset_rows(meta):
        next_asset = dict(asset)
        if (next_asset.get("asset_key") or next_asset.get("filename")) == asset_key:
            next_asset["deleted"] = True
        assets.append(next_asset)
    meta["generated_assets"] = assets
    catalog[_XML_KEY] = meta
    config[_CATALOG_KEY] = catalog
    return config


def mark_xlsx_source_deleted(row: dict[str, Any]) -> dict[str, Any]:
    config = dict(row.get("config") or {})
    catalog = dict(config.get(_CATALOG_KEY) or {})
    meta = dict(catalog.get(_XLSX_KEY) or {})
    meta["deleted"] = True
    for asset in _asset_rows(meta):
        asset["deleted"] = True
    catalog[_XLSX_KEY] = meta
    config[_CATALOG_KEY] = catalog
    return config


def mark_xlsx_asset_deleted(row: dict[str, Any], asset_key: str) -> dict[str, Any]:
    config = dict(row.get("config") or {})
    catalog = dict(config.get(_CATALOG_KEY) or {})
    meta = dict(catalog.get(_XLSX_KEY) or {})
    assets = []
    for asset in _asset_rows(meta):
        next_asset = dict(asset)
        if (next_asset.get("asset_key") or next_asset.get("filename")) == asset_key:
            next_asset["deleted"] = True
        assets.append(next_asset)
    meta["generated_assets"] = assets
    catalog[_XLSX_KEY] = meta
    config[_CATALOG_KEY] = catalog
    return config


def xlsx_download_payload(
    row: dict[str, Any],
    *,
    asset_key: str | None = None,
    payload_rows_by_dataset: dict[str, list[dict[str, Any]]] | None = None,
    counts: Counter[tuple[str, str]] | None = None,
) -> tuple[bytes, str, str] | None:
    """Same shape as xml_download_payload — download the original workbook
    (asset_key=None) or one generated sheet CSV (asset_key set). Unlike XML's
    legacy-prefix case, an xlsx catalog row always carries content_b64 for
    the source workbook itself, so there's no synthetic-manifest fallback
    path to mirror."""
    payload_rows_by_dataset = payload_rows_by_dataset or {}
    meta = _xlsx_meta(row)
    if meta is None or meta.get("deleted"):
        return None
    if asset_key is None:
        content_b64 = meta.get("content_b64")
        if not content_b64:
            return None
        return (
            base64.b64decode(content_b64),
            meta.get("source_filename") or row.get("name") or "source.xlsx",
            meta.get("content_type")
            or "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    for asset in _active_assets(meta):
        current_key = asset.get("asset_key") or asset.get("filename")
        if current_key != asset_key:
            continue
        content_b64 = asset.get("content_b64")
        if not content_b64:
            csv_bytes = _csv_bytes_from_payload_rows(payload_rows_by_dataset.get(str(asset.get("dataset") or "")))
            if csv_bytes is None:
                return None
            return (
                csv_bytes,
                asset.get("filename") or f"{asset_key}.csv",
                asset.get("content_type") or "text/csv",
            )
        return (
            base64.b64decode(content_b64),
            asset.get("filename") or f"{asset_key}.csv",
            asset.get("content_type") or "text/csv",
        )
    return None


def xml_download_payload(
    row: dict[str, Any],
    *,
    asset_key: str | None = None,
    payload_rows_by_dataset: dict[str, list[dict[str, Any]]] | None = None,
    counts: Counter[tuple[str, str]] | None = None,
) -> tuple[bytes, str, str] | None:
    payload_rows_by_dataset = payload_rows_by_dataset or {}
    meta = _xml_meta(row)
    if meta is None or meta.get("deleted"):
        return None
    if asset_key is None:
        content_b64 = meta.get("content_b64")
        if not content_b64:
            if not _active_assets(meta):
                return None
            counts = counts or Counter()
            root = ET.Element("aryxXmlSource", {
                "name": str(meta.get("source_filename") or row.get("name") or "source.xml"),
                "legacy": "true" if meta.get("legacy_prefix") else "false",
            })
            assets_el = ET.SubElement(root, "generatedAssets")
            for asset in _active_assets(meta):
                dataset = str(asset.get("dataset") or "")
                ET.SubElement(assets_el, "asset", {
                    "dataset": dataset,
                    "filename": str(asset.get("filename") or f"{dataset}.csv"),
                    "ontologyType": str(asset.get("ontology_type") or dataset.rsplit("_", 1)[-1]),
                    "recordCount": str(counts.get(("csv", dataset), 0)),
                })
            return (
                ET.tostring(root, encoding="utf-8", xml_declaration=True),
                meta.get("source_filename") or row.get("name") or "source.xml",
                "application/xml",
            )
        return (
            base64.b64decode(content_b64),
            meta.get("source_filename") or row.get("name") or "source.xml",
            meta.get("content_type") or "application/xml",
        )
    for asset in _active_assets(meta):
        current_key = asset.get("asset_key") or asset.get("filename")
        if current_key != asset_key:
            continue
        content_b64 = asset.get("content_b64")
        if not content_b64:
            csv_bytes = _csv_bytes_from_payload_rows(payload_rows_by_dataset.get(str(asset.get("dataset") or "")))
            if csv_bytes is None:
                return None
            return (
                csv_bytes,
                asset.get("filename") or f"{asset_key}.csv",
                asset.get("content_type") or "text/csv",
            )
        return (
            base64.b64decode(content_b64),
            asset.get("filename") or f"{asset_key}.csv",
            asset.get("content_type") or "text/csv",
        )
    return None


def _display_kind(system: str, dataset: str) -> str:
    if system == "csv" or dataset.endswith(".csv"):
        return "Structured CSV"
    if system in {"rest", "api"}:
        return "REST API"
    if system == "document" or dataset.endswith((".pdf", ".docx", ".xml")):
        return "Document"
    return system.replace("_", " ").title()
