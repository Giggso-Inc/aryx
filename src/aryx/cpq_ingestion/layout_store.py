"""Persist an uploaded CPQ layout-export file (.txt/.json) to
``aryx_cpq_layout_file`` -- the per-workspace, uploaded replacement for
the old hardcoded ``config_layouts/`` directory (see
CPQ_LAYOUT_FILE_STORAGE_MIGRATION_PLAN_2026-09-30.md).

Write side only. The read side (``OracleLayoutFileSource``) lives in
``aryx.cpq.layout_source`` -- kept there, not here, since it's consumed
by the CPQ engine regardless of whether cpq_ingestion is installed, the
same reasoning ``raw_graph/store.py`` sits under cpq_ingestion/ while
its downstream consumer (``CpqEngine``) does not.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from aryx.config import get_settings
from aryx.queries import load
from aryx.raven_log import raven_log
from aryx.worker.job_partial import note_hidden
from aryx.store.datasource_store import DatasourceStore
from aryx.store.pool import get_pool

logger = logging.getLogger(__name__)

# Datasource "kind" for a stored layout file -- surfaced on the Data >
# Sources catalog page via source_catalog_meta._display_kind(), so an
# uploaded .txt/.json layout export shows up there like any other
# upload, not just in aryx_cpq_layout_file (invisible to that page).
_DATASOURCE_KIND = "cpq_layout"

# Same shape as DiscoveryPayloadTooLarge (discovery_store_codec.py) but sized
# for this table's actual data: the largest real layout export today is
# ConfigLayout_SVX.txt at 8,313 lines / a few hundred KB -- 50MB gives
# generous headroom without inheriting discovery's 512MB ceiling, which was
# sized for multi-file tabular-source dedup, an unrelated workload.
_MAX_LAYOUT_FILE_BYTES = 50 * 1024 * 1024


class CpqLayoutFileTooLarge(ValueError):
    """Raised when an uploaded layout file exceeds _MAX_LAYOUT_FILE_BYTES."""


def catalog_prefix_from_filename(filename: str) -> str:
    """Derive a catalog_prefix from an uploaded layout file's name when the
    caller doesn't supply one explicitly -- the raw stem, unmodified (NOT
    `_stem_type`'s PascalCase-singularized ontology-type derivation, which
    is for classifying CSV rows into entity types, an unrelated purpose).
    Real ingested catalog_prefix values are themselves raw, filename-derived
    strings (see layout_source.py's own docstring), so this keeps upload-
    derived and ingestion-derived catalog_prefix values in the same shape.
    """
    return Path(filename).stem


def _default_variant() -> str:
    from aryx.cpq.layout_source import DEFAULT_LAYOUT_VARIANT  # noqa: PLC0415 -- see layout_variant_from_content
    return DEFAULT_LAYOUT_VARIANT


def layout_variant_from_content(content: str) -> str:
    """Variant key for a layout export: its own top-level `variableName`
    (opaque string, read from the data). Invalid JSON, a non-object, or a
    missing/blank/non-string name -> the sentinel (never NULL or '')."""
    # Lazy: importing aryx.cpq pulls the whole engine chain (see the
    # invalidate_layout_cache note in store_layout_file).
    from aryx.cpq.layout_source import DEFAULT_LAYOUT_VARIANT  # noqa: PLC0415
    try:
        data = json.loads(content)
    except (ValueError, TypeError):
        return DEFAULT_LAYOUT_VARIANT
    name = data.get("variableName") if isinstance(data, dict) else None
    if isinstance(name, str) and name.strip():
        return name.strip()
    return DEFAULT_LAYOUT_VARIANT


def store_layout_file(
    data: bytes,
    filename: str,
    *,
    workspace_id: int,
    dsn: str,
    catalog_prefix: str | None = None,
) -> str:
    """Upsert one layout file's content for (workspace_id, catalog_prefix,
    variant), the variant being the file's own `variableName` -- a
    re-upload replaces only that variant, other variants stay.

    Returns the catalog_prefix actually stored under (either the caller's
    explicit value, or the filename-derived default) so the caller can log
    or surface it. Raises CpqLayoutFileTooLarge if `data` exceeds the size
    guard -- callers should catch this and log+continue rather than fail
    the whole upload batch over one oversized file, matching the raw-graph
    write's best-effort posture (see cpq_ingestion/pipeline.py).
    """
    t0 = time.monotonic()
    if len(data) > _MAX_LAYOUT_FILE_BYTES:
        raven_log("WARN", "P3", "ingest.layout.too_large layout file over size guard",
                  error_code="ARYX_ING_LAYOUT_SKIPPED",
                  context={"filename": filename, "limit": _MAX_LAYOUT_FILE_BYTES, "measured": len(data),
                           "decision": "refuse", "reason_code": "TOO_LARGE"})
        raise CpqLayoutFileTooLarge(
            f"layout file {filename!r} is {len(data)} bytes -- exceeds "
            f"the {_MAX_LAYOUT_FILE_BYTES} byte guard"
        )
    prefix = catalog_prefix or catalog_prefix_from_filename(filename)
    raven_log("DEBUG", "P4", "ingest.layout.prefix catalog prefix chosen",
              context={"filename": filename, "catalog_prefix": prefix,
                       "selected_option": "explicit" if catalog_prefix else "filename_stem",
                       "available_options": ["explicit", "filename_stem"], "reason_code": "CATALOG_PREFIX",
                       "bytes": len(data), "limit": _MAX_LAYOUT_FILE_BYTES})
    content = data.decode("utf-8")
    # Flag off: one layout per catalog as before, so a re-upload always replaces the 'default'
    # row the reader serves; the variant key is derived only when variants are enabled.
    variant = (
        layout_variant_from_content(content)
        if get_settings().cpq_layout_variants_enabled
        else _default_variant()
    )
    params = {
        "layout_id": uuid.uuid4().hex,
        "workspace_id": workspace_id,
        "catalog_prefix": prefix,
        "variant": variant,
        "filename": filename,
        "content_clob": content,
        "uploaded_at": datetime.now(tz=timezone.utc),
    }
    pool = get_pool(dsn)
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(load("upsert_cpq_layout_file"), params)
    logger.info(
        "cpq_ingestion: stored layout file workspace_id=%d catalog_prefix=%r "
        "variant=%r filename=%r bytes=%d", workspace_id, prefix, variant, filename, len(data),
    )
    # Register as a datasource so the file shows up on the Data > Sources
    # catalog page like any other upload -- previously only written to
    # aryx_cpq_layout_file, which that page never reads. ensure() is a
    # get-or-create keyed on (workspace_id, filename), so a re-upload of
    # the same file is a no-op here, not a duplicate row. Best-effort: a
    # datasource-registration failure must never fail the actual layout
    # storage that already succeeded above.
    try:
        DatasourceStore(dsn).ensure(workspace_id, filename[:255], _DATASOURCE_KIND)
    except Exception as ds_exc:  # noqa: BLE001
        logger.warning(
            "cpq_ingestion: datasource ensure failed for layout file %r",
            filename, exc_info=True,
        )
        note_hidden()
        raven_log("WARN", "P3", "ingest.datasource.register_failed layout file not in Data > Sources",
                  error_code="ARYX_ING_DATASOURCE_FAILED",
                  context={"dependency_name": "adb", "operation": "datasource_ensure",
                           "duration_ms": int((time.monotonic() - t0) * 1000), "result": "error",
                           "error_class": type(ds_exc).__name__, "attempt": 1,
                           "filename": filename[:255], "kind": _DATASOURCE_KIND})
    # Without this, a re-upload replacing an already-queried (workspace_id,
    # catalog_prefix) pair would keep serving the OLD cached value for the
    # rest of this process's lifetime -- engine_caches.py's layout caches
    # have no TTL. Lazy import: avoids pulling the whole heavy cpq/ engine
    # module chain into this otherwise-small write-side module at import
    # time for callers that never touch it.
    from aryx.cpq.engine_caches import invalidate_layout_cache  # noqa: PLC0415
    invalidate_layout_cache(workspace_id, prefix)
    raven_log("DEBUG", "P4", "ingest.layout.stored layout file upserted and cache invalidated",
              context={"filename": filename, "catalog_prefix": prefix, "workspace_id": workspace_id,
                       "bytes": len(data), "duration_ms": int((time.monotonic() - t0) * 1000)})
    return prefix
