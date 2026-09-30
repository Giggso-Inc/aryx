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

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from aryx.queries import load
from aryx.store.pool import get_pool

logger = logging.getLogger(__name__)

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


def store_layout_file(
    data: bytes,
    filename: str,
    *,
    workspace_id: int,
    dsn: str,
    catalog_prefix: str | None = None,
) -> str:
    """Upsert one layout file's content for (workspace_id, catalog_prefix).

    Returns the catalog_prefix actually stored under (either the caller's
    explicit value, or the filename-derived default) so the caller can log
    or surface it. Raises CpqLayoutFileTooLarge if `data` exceeds the size
    guard -- callers should catch this and log+continue rather than fail
    the whole upload batch over one oversized file, matching the raw-graph
    write's best-effort posture (see cpq_ingestion/pipeline.py).
    """
    if len(data) > _MAX_LAYOUT_FILE_BYTES:
        raise CpqLayoutFileTooLarge(
            f"layout file {filename!r} is {len(data)} bytes -- exceeds "
            f"the {_MAX_LAYOUT_FILE_BYTES} byte guard"
        )
    prefix = catalog_prefix or catalog_prefix_from_filename(filename)
    content = data.decode("utf-8")
    params = {
        "layout_id": uuid.uuid4().hex,
        "workspace_id": workspace_id,
        "catalog_prefix": prefix,
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
        "filename=%r bytes=%d", workspace_id, prefix, filename, len(data),
    )
    # Without this, a re-upload replacing an already-queried (workspace_id,
    # catalog_prefix) pair would keep serving the OLD cached value for the
    # rest of this process's lifetime -- engine_caches.py's layout caches
    # have no TTL. Lazy import: avoids pulling the whole heavy cpq/ engine
    # module chain into this otherwise-small write-side module at import
    # time for callers that never touch it.
    from aryx.cpq.engine_caches import invalidate_layout_cache  # noqa: PLC0415
    invalidate_layout_cache(workspace_id, prefix)
    return prefix
