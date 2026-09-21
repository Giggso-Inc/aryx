"""Soft-delete + download-payload helpers for XML/XLSX catalog entries.

Split out of `source_catalog.py` (Raven Style Compliance Plan, Phase 2a,
2026-09-03).
"""
from __future__ import annotations

import base64
import xml.etree.ElementTree as ET
from collections import Counter
from typing import Any

from aryx.source.source_catalog_meta import (
    _CATALOG_KEY,
    _XLSX_KEY,
    _XML_KEY,
    _active_assets,
    _asset_rows,
    _csv_bytes_from_payload_rows,
    _xlsx_meta,
    _xml_meta,
)


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
    legacy-prefix case, there's no synthetic-manifest fallback for a missing
    top-level content_b64 here: a workbook over _MAX_INLINE_CONTENT_BYTES
    (2026-09-16) has content_b64=None just like a legacy row would, and this
    function simply returns None (download unavailable) rather than
    reconstructing anything — xml_download_payload's manifest path has no
    xlsx equivalent."""
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
