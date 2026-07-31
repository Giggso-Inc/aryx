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

`data` is stored as gzip-compressed JSON in a BYTEA column (migration
0036), not live JSONB — see DiscoveryPayloadTooLarge's docstring for why:
a large multi-file tabular batch's serialized JSONB array can exceed
Postgres's own hard, non-configurable ~256MB limit on a single JSONB
array's size. BYTEA has no such array-size restriction, and gzip shrinks
text-heavy CSV payloads substantially before they're ever written.

Postgres-only for now (no Oracle migration/query variant) — matches this
store's existing DSN-driven backend selection elsewhere, but ARYX_DB_BACKEND=oci
deployments won't get durability from this fix until an Oracle variant is
added.
"""
from __future__ import annotations

import base64
import gzip
import json
import logging
from typing import Any

from aryx.config import get_settings
from aryx.models import RawRecord
from aryx.queries import load
from aryx.store.pool import get_pool

logger = logging.getLogger(__name__)


class DiscoveryPayloadTooLarge(ValueError):
    """Raised when a discovery result is too large to persist in one write.

    Two real, confirmed incidents motivate this guard:
    - A 32-file BigMachines CSV catalog batch's serialized payload was large
      enough to overrun Postgres's wire-protocol fixed-size message-length
      framing, killing the connection outright with "invalid message
      length" instead of a normal query error.
    - A 33-file SL3500e batch separately hit a second, harder wall: when
      `data` was stored as live JSONB, Postgres hard-caps a single JSONB
      array's serialized size at 268,435,455 bytes (~256MB) —
      `psycopg.errors.ProgramLimitExceeded: total size of jsonb array
      elements exceeds the maximum of 268435455 bytes` — a fixed
      database-engine limit, not a Postgres setting, so raising the old
      JSONB-based guard past ~256MB could never have helped.

    Migration 0036 closed the second wall structurally: `data` is now
    gzip-compressed JSON in a BYTEA column, which has no JSONB-array-size
    restriction (Postgres TOASTs a BYTEA value up to ~1GB), and compression
    shrinks text-heavy CSV payloads substantially on top of that headroom.
    This guard remains for the first wall (and as a sane upper bound in
    general) — it now measures the size AFTER gzip compression against
    `settings.discovery_max_payload_mb`, so an oversized batch still fails
    as a clean, catchable error — surfaced as a normal "failed" job status
    by doc_discover_api._read_job's except block — instead of crashing the
    connection or failing deep inside a database write.
    """


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
    """Persist a discovery result — durable across process restarts/crashes.

    Serialized as JSON, then gzip-compressed, then written as BYTEA
    (migration 0036) — see DiscoveryPayloadTooLarge's docstring for why
    live JSONB couldn't hold an oversized multi-file batch at all.

    Raises DiscoveryPayloadTooLarge instead of attempting the write when
    the COMPRESSED payload exceeds settings.discovery_max_payload_mb.
    """
    settings = get_settings()
    workspace_id = data.get("workspace_id", 1)
    payload = _serialize(data)
    raw_json = json.dumps(payload, default=str).encode("utf-8")
    compressed = gzip.compress(raw_json)
    max_bytes = settings.discovery_max_payload_mb * 1024 * 1024
    if len(compressed) > max_bytes:
        logger.warning(
            "discoveries.put did=%s REJECTED payload_size=%d bytes "
            "raw=%d bytes (limit=%d) mentions=%d tabular=%d — split into a "
            "smaller batch or raise ARYX_DISCOVERY_MAX_PAYLOAD_MB",
            discovery_id, len(compressed), len(raw_json), max_bytes,
            len(data.get("mentions", [])), len(data.get("tabular", [])),
        )
        raise DiscoveryPayloadTooLarge(
            f"Discovery result is {len(compressed) / 1024 / 1024:.1f} MB "
            f"compressed ({len(raw_json) / 1024 / 1024:.1f} MB raw), over "
            f"the {settings.discovery_max_payload_mb} MB limit for a single "
            f"batch. Upload fewer files at once, or raise "
            f"ARYX_DISCOVERY_MAX_PAYLOAD_MB if your deployment's Postgres "
            f"connection can handle a larger single write."
        )
    pool = get_pool(settings.rdb_dsn)
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(load("upsert_discovery"), (discovery_id, workspace_id, compressed))
    logger.info(
        "discoveries.put did=%s mentions=%d tabular=%d payload_size=%d raw=%d",
        discovery_id, len(data.get("mentions", [])), len(data.get("tabular", [])),
        len(compressed), len(raw_json),
    )


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
    payload = json.loads(gzip.decompress(bytes(row[0])).decode("utf-8"))
    return _deserialize(payload)


def drop(discovery_id: str) -> None:
    """Forget a discovery result."""
    pool = get_pool(get_settings().rdb_dsn)
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(load("delete_discovery"), (discovery_id,))
            existed = cur.rowcount > 0
    if existed:
        logger.info("discoveries.drop did=%s", discovery_id)
