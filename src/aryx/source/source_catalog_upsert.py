"""Config builders + upsert/find helpers for XML/XLSX/generic catalog entries.

Split out of `source_catalog.py` (Raven Style Compliance Plan, Phase 2a,
2026-09-03).
"""
from __future__ import annotations

import base64
import logging
from datetime import UTC, datetime
from typing import Any

from aryx.source.source_catalog_meta import (
    _CATALOG_KEY,
    _GENERIC_KEY,
    _XLSX_KEY,
    _XML_KEY,
    _asset_rows,
    _generic_meta,
    _xml_meta,
)

logger = logging.getLogger(__name__)

# Postgres hard limit: a single jsonb scalar string cannot exceed
# 268,435,455 bytes (psycopg.errors.ProgramLimitExceeded: "string too long
# to represent as jsonb string"). Real incident 2026-09-16: an XML upload's
# base64-encoded bytes (raw size * 4/3) exceeded this, crashing the confirm
# job for the WHOLE batch at DatasourceStore.add()'s Json(config) write --
# xml_catalog_config/xml_asset_record/xlsx_catalog_config/xlsx_asset_record
# all embed a full file/asset's bytes as one base64 JSONB string.
#
# Capped well under the hard limit (170 MiB raw -> ~227 MiB encoded) rather
# than right up against it, since JSON/network overhead on top of the raw
# base64 string isn't free either.
#
# When raw content exceeds this cap, content_b64 is omitted (None) rather
# than raising -- every read site (xml_download_payload, xlsx_download_
# payload, _preview_rows) already has a documented fallback for a missing
# content_b64 (the "legacy" manifest-reconstruction path for XML, or
# rebuilding a CSV asset from currently-ingested rows), so this degrades
# original-file download/preview for oversized files instead of failing
# the entire confirm job.
_MAX_INLINE_CONTENT_BYTES = 170 * 1024 * 1024


def _safe_content_fields(raw_bytes: bytes, *, source_filename: str) -> dict[str, Any]:
    """{"content_b64": <str>}, or {"content_b64": None, "content_omitted_
    oversized": True} if `raw_bytes` would exceed Postgres's single-jsonb-
    string limit -- see _MAX_INLINE_CONTENT_BYTES above.

    The explicit content_omitted_oversized marker matters: without it, a
    real current row with content_b64 omitted for size is indistinguishable
    from a genuine pre-migration legacy placeholder row (which also has no
    content_b64) to find_legacy_xml_row's fallback heuristic (not content_b64
    + assets + matching filename) -- confirmed exploitable in PR #334's own
    review (2026-09-16): a real oversized upload whose generated-asset
    dataset names happen to share the file's own stem would get matched as
    "legacy" and have its real config silently overwritten by
    upsert_legacy_xml_catalog_entry. Callers merge this dict's keys into
    their config dict (`**_safe_content_fields(...)`) rather than setting
    a single "content_b64" key directly, so the marker is only ever present
    when it's true -- never a stray "content_omitted_oversized": False on
    every normal-sized row.
    """
    if len(raw_bytes) > _MAX_INLINE_CONTENT_BYTES:
        logger.warning(
            "source_catalog: omitting content_b64 for %r -- %d raw bytes "
            "exceeds the %d byte inline cap (Postgres's jsonb single-string "
            "limit); original-file download/preview falls back to the "
            "reconstructed-from-assets path instead",
            source_filename, len(raw_bytes), _MAX_INLINE_CONTENT_BYTES,
        )
        return {"content_b64": None, "content_omitted_oversized": True}
    return {"content_b64": base64.b64encode(raw_bytes).decode("ascii")}


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
                **_safe_content_fields(xml_bytes, source_filename=source_filename),
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
        **_safe_content_fields(content_bytes, source_filename=filename),
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
                **_safe_content_fields(xlsx_bytes, source_filename=source_filename),
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
        **_safe_content_fields(content_bytes, source_filename=filename),
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
    """A row with legacy_prefix set is unambiguously a pre-migration
    placeholder. The fallback branch below (no legacy_prefix, but no
    content_b64 either) used to assume that combination was ALSO always a
    legacy row -- true only because every real upload always had a
    content_b64 before the 2026-09-16 size cap. A real, current oversized
    upload now also has content_b64=None, and can share the fallback's
    filename/asset-shape match if its generated-asset dataset names happen
    to collide with `prefix` (confirmed exploitable in PR #334's own
    review). content_omitted_oversized (set by _safe_content_fields)
    distinguishes "no content because legacy placeholder" from "no content
    because a real file was too large to inline" -- only the former may
    match here.
    """
    expected_name = f"{prefix}.xml"
    for row in datasources:
        meta = _xml_meta(row)
        if meta is None:
            continue
        if meta.get("legacy_prefix") == prefix:
            return row
        if (
            not meta.get("content_b64")
            and not meta.get("content_omitted_oversized")
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
