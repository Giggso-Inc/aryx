"""Pure meta-extraction helpers shared by every source_catalog builder.

Split out of `source_catalog.py` (Raven Style Compliance Plan, Phase 2a,
2026-09-03).
"""
from __future__ import annotations

import base64
import csv
import io
from collections import Counter
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


def _display_kind(system: str, dataset: str) -> str:
    if system == "csv" or dataset.endswith(".csv"):
        return "Structured CSV"
    if system in {"rest", "api"}:
        return "REST API"
    if system == "document" or dataset.endswith((".pdf", ".docx", ".xml")):
        return "Document"
    if system == "cpq_layout":
        return "CPQ Layout File"
    return system.replace("_", " ").title()
