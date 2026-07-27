"""Durable (Postgres-backed) store of document-discovery results awaiting
user confirmation.

The read step extracts mentions and stashes them here keyed by a discovery
id; the confirm step retrieves and ingests the user-approved subset.

Was previously a plain in-process dict (`_STORE`) — the read job's progress
callback genuinely flushed a growing partial snapshot on every N chunks
(see doc_discover_api._build_read_progress), but flushing into a dict that
lives only in this worker process's memory meant a crash or restart
partway through a long document still wiped every mention extracted so
far, even though the job's own stage/pct (durable in aryx_job) kept
showing accurate-looking progress for data that no longer existed. Now
backed by aryx_discovery (migration 0035), which survives a process
restart the same way aryx_job already does.

RawRecord mentions and raw file bytes (tabular plans' `data`/`source_bytes`)
aren't natively JSON-serialisable, so they're encoded on the way in and
decoded on the way out — everything else in the payload passes through
unchanged.

Postgres-only for now (no Oracle migration/query variant) — matches this
store's existing DSN-driven backend selection elsewhere, but ARYX_DB_BACKEND=oci
deployments won't get durability from this fix until an Oracle variant is
added.
"""
from __future__ import annotations

import base64
import logging
from typing import Any

from psycopg.types.json import Json

from aryx.config import get_settings
from aryx.models import RawRecord
from aryx.queries import load
from aryx.store.pool import get_pool

logger = logging.getLogger(__name__)


def _serialize_mentions(mentions: list[Any]) -> list[dict]:
    return [m.model_dump(mode="json") if isinstance(m, RawRecord) else m for m in mentions]


def _deserialize_mentions(mentions: list[Any]) -> list[RawRecord]:
    return [m if isinstance(m, RawRecord) else RawRecord.model_validate(m) for m in mentions]


def _b64_encode_bytes_fields(plan: dict, fields: tuple[str, ...]) -> dict:
    out = dict(plan)
    for field in fields:
        val = out.get(field)
        if isinstance(val, (bytes, bytearray)):
            out[field] = base64.b64encode(val).decode("ascii")
            out[f"_{field}_b64"] = True
    return out


def _b64_decode_bytes_fields(plan: dict, fields: tuple[str, ...]) -> dict:
    out = dict(plan)
    for field in fields:
        if out.pop(f"_{field}_b64", False):
            out[field] = base64.b64decode(out[field])
    return out


_TABULAR_BYTES_FIELDS = ("data", "source_bytes")


def _serialize(data: dict[str, Any]) -> dict[str, Any]:
    out = dict(data)
    if "mentions" in out:
        out["mentions"] = _serialize_mentions(out["mentions"])
    if "tabular" in out:
        out["tabular"] = [_b64_encode_bytes_fields(p, _TABULAR_BYTES_FIELDS) for p in out["tabular"]]
    return out


def _deserialize(data: dict[str, Any]) -> dict[str, Any]:
    out = dict(data)
    if "mentions" in out:
        out["mentions"] = _deserialize_mentions(out["mentions"])
    if "tabular" in out:
        out["tabular"] = [_b64_decode_bytes_fields(p, _TABULAR_BYTES_FIELDS) for p in out["tabular"]]
    return out


def put(discovery_id: str, data: dict[str, Any]) -> None:
    """Persist a discovery result — durable across process restarts/crashes."""
    workspace_id = data.get("workspace_id", 1)
    payload = _serialize(data)
    pool = get_pool(get_settings().rdb_dsn)
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(load("upsert_discovery"), (discovery_id, workspace_id, Json(payload)))
    logger.info("discoveries.put did=%s mentions=%d tabular=%d",
                discovery_id, len(data.get("mentions", [])), len(data.get("tabular", [])))


def get(discovery_id: str) -> dict[str, Any] | None:
    """Return a discovery result, or None if unknown/expired."""
    pool = get_pool(get_settings().rdb_dsn)
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(load("select_discovery"), (discovery_id,))
            row = cur.fetchone()
    if row is None:
        logger.warning("discoveries.get did=%s not found (unknown or expired)", discovery_id)
        return None
    return _deserialize(row[0])


def drop(discovery_id: str) -> None:
    """Forget a discovery result."""
    pool = get_pool(get_settings().rdb_dsn)
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(load("delete_discovery"), (discovery_id,))
            existed = cur.rowcount > 0
    if existed:
        logger.info("discoveries.drop did=%s", discovery_id)
