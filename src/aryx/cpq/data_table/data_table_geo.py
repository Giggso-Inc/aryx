"""Country -> region and country -> RTTE/non-RTTE/TA lookups from the ingested
``newCountryRegion`` and ``rtteTAReference`` Data Tables (plan F5,
docs/oci-oracle/CONFIG_DATA_REQUIRED_FIELDS_INGEST_AND_FIX_PLAN_2026-10-05.md).

Pure reads, shape-detected like every other Data Table here (no table names).
Callers gate on ``Settings.cpq_country_region_table_enabled``; ``None`` always
means "no ingested row", so the caller keeps its existing fallback
(`_COUNTRY_TO_REGION`) instead of guessing.
"""
from __future__ import annotations

from typing import Any

from aryx.cpq.data_table.data_table_loader import _SHAPE_SCAN_CACHES, _cached_shape_scan
from aryx.cpq.data_table.data_table_shapes import _is_country_region_shaped, _is_rtte_ta_shaped

_COUNTRY_REGION_CACHE: dict[tuple[int, str], tuple[float, list[dict[str, Any]]]] = {}
_COUNTRY_REGION_CACHE_LAST_SEEN_MARKER: list[float | None] = [None]
_RTTE_TA_CACHE: dict[tuple[int, str], tuple[float, list[dict[str, Any]]]] = {}
_RTTE_TA_CACHE_LAST_SEEN_MARKER: list[float | None] = [None]
_SHAPE_SCAN_CACHES.extend([_COUNTRY_REGION_CACHE, _RTTE_TA_CACHE])

# column -> label when the setter script is not available (kept in column order)
DEFAULT_RTTE_LABELS: dict[str, str] = {"RTTE": "RTTE", "nonRTTE": "NON RTTE", "TA": "TA"}


def _load_rows(
    store: dict, marker: list[float | None], pred: Any, label: str,
    workspace_id: int, catalog_prefix: str, cache: dict[tuple, Any] | None,
) -> list[dict[str, Any]]:
    key = (workspace_id, catalog_prefix, label)
    if cache is not None and key in cache:
        return cache[key]
    rows = _cached_shape_scan(store, marker, workspace_id, catalog_prefix, pred, label)
    if cache is not None:
        cache[key] = rows
    return rows


def _norm(country: str) -> str:
    return (country or "").strip().upper()


def resolve_country_region(
    country: str, workspace_id: int, catalog_prefix: str = "",
    cache: dict[tuple, Any] | None = None,
) -> str | None:
    """Region code (EA, LA, NA, ME, AP, ...) the ingested country table assigns
    to the 2-letter `country` code; None when no row names it."""
    code = _norm(country)
    if not code:
        return None
    rows = _load_rows(
        _COUNTRY_REGION_CACHE, _COUNTRY_REGION_CACHE_LAST_SEEN_MARKER,
        _is_country_region_shaped, "_load_country_region_rows", workspace_id, catalog_prefix, cache,
    )
    for row in rows:
        if _norm(str(row.get("countryCode") or "")) == code:
            region = str(row.get("region") or "").strip()
            return region or None
    return None


def resolve_rtte_flag(
    country: str, workspace_id: int, catalog_prefix: str = "",
    cache: dict[tuple, Any] | None = None, labels: dict[str, str] | None = None,
) -> str | None:
    """The label of the first flag column set to Yes for `country`, or None.

    `labels` maps a flag column to the text it stands for (the setter rule's own
    script defines it; see ``table_lookup_script``). Without it the default
    mapping below is used."""
    code = _norm(country)
    if not code:
        return None
    rows = _load_rows(
        _RTTE_TA_CACHE, _RTTE_TA_CACHE_LAST_SEEN_MARKER,
        _is_rtte_ta_shaped, "_load_rtte_ta_rows", workspace_id, catalog_prefix, cache,
    )
    for row in rows:
        if _norm(str(row.get("countryCode") or "")) != code:
            continue
        for col, label in (labels or DEFAULT_RTTE_LABELS).items():
            if str(row.get(col) or "").strip().upper() in ("YES", "Y"):
                return label
        return None
    return None
