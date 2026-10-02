"""DB-backed document-discovery store: replaces the in-memory dict in discoveries.py.

Persists /admin/docs/read results so discoveries survive container restarts and
scale across multiple API instances.  Works on both Postgres and Oracle ADB 26ai
via the shared pool factory — oracle_pool.py handles all SQL translation.

As of the Raven Style Compliance Plan's Phase 2b (2026-09-03), the pure
JSON codec helpers moved to `discovery_store_codec.py` (zero patch risk).
`DiscoveryStore` itself stays as a deliberate, documented exception:
`tests/test_discovery_store.py`'s `setup_module` patches
`aryx.store.discovery_store.load` ONCE for the whole test module, and
nearly every method (`put`/`get`/`get_summary`/`drop`/`mark_confirmed`/
`update_confirm_state`/`list_recent`) calls `load(...)` — moving any one
of them to a module with its own `from aryx.queries import load` import
would silently stop seeing that patch.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from aryx.config import get_settings
from aryx.queries import load
from aryx.store.discovery_store_codec import (
    DiscoveryPayloadTooLarge,
    _deserialize_data,
    _row_to_dict,
    _serialize_data,
)
from aryx.store.pool import get_pool

__all__ = ["DiscoveryPayloadTooLarge", "DiscoveryStore", "_deserialize_data", "_serialize_data"]

logger = logging.getLogger(__name__)


class DiscoveryStore:
    """Persists document discoveries (Postgres + Oracle ADB 26ai)."""

    def __init__(self, dsn: str) -> None:
        """Acquire the shared connection pool for this DSN."""
        self._pool = get_pool(dsn)

    def put(
        self,
        discovery_id: str,
        workspace_id: int,
        data: dict,
        summary: dict,
        file_count: int,
    ) -> None:
        """Upsert a discovery row.  Does NOT overwrite status or confirm_state on conflict."""
        data_json = _serialize_data(data)
        max_bytes = get_settings().discovery_max_payload_mb * 1024 * 1024
        if len(data_json) > max_bytes:
            raise DiscoveryPayloadTooLarge(
                f"discovery {discovery_id} payload is {len(data_json)} bytes "
                f"(compressed) — exceeds discovery_max_payload_mb="
                f"{get_settings().discovery_max_payload_mb}MB"
            )
        params = {
            "discovery_id": discovery_id,
            "workspace_id": workspace_id,
            "data_json":    data_json,
            "summary_json": json.dumps(summary),
            "file_count":   file_count,
            "created_at":   datetime.now(tz=timezone.utc),
        }
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(load("upsert_discovery"), params)
        logger.info("discovery put discovery_id=%s workspace_id=%d files=%d",
                    discovery_id, workspace_id, file_count)

    def get(self, discovery_id: str, workspace_id: int) -> dict[str, Any] | None:
        """Return a discovery by ID, scoped to the calling workspace.

        Returns None when the row doesn't exist OR belongs to a different workspace
        (multi-tenant isolation — prevents cross-workspace ID guessing).
        """
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(load("select_discovery"), (discovery_id, workspace_id))
                row = cur.fetchone()
        return _row_to_dict(row) if row else None

    def get_summary(self, discovery_id: str, workspace_id: int) -> dict[str, Any] | None:
        """Return just the summary for a discovery, scoped to the calling workspace.

        Deliberately avoids fetching/deserializing data_json — that column holds
        every raw file's bytes (base64-encoded) for the whole discovery and can
        reach hundreds of MB for a multi-file tabular ingest (confirmed live: a
        30-file discovery's data_json was 257MB), making the full get() effectively
        hang for the review-step UI, which only ever needs the small summary.
        """
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(load("select_discovery_summary"), (discovery_id, workspace_id))
                row = cur.fetchone()
        if not row:
            return None
        return json.loads(row[0] or "{}")

    def get_status(self, discovery_id: str, workspace_id: int) -> str | None:
        """Return just the status column, scoped to the calling workspace.

        Cheap existence + workspace-ownership check for actions (like dismiss)
        that need to branch on status without paying for the full get()'s
        data_json deserialization or even get_summary()'s JSON parse.
        """
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(load("select_discovery_status"), (discovery_id, workspace_id))
                row = cur.fetchone()
        return row[0] if row else None

    def drop(self, discovery_id: str) -> None:
        """Delete a discovery row (no workspace guard — internal cleanup only)."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(load("delete_discovery"), (discovery_id,))

    def set_status(self, discovery_id: str, status: str) -> None:
        """Update the status column for a discovery row."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE aryx_discovery SET status = %s WHERE discovery_id = %s",
                    (status, discovery_id),
                )

    def mark_confirmed(self, discovery_id: str, job_id: str) -> None:
        """Transition status → confirmed and stamp confirmed_at."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    load("mark_confirmed_discovery"),
                    (datetime.now(tz=timezone.utc), discovery_id),
                )
        logger.info("discovery confirmed discovery_id=%s job_id=%s", discovery_id, job_id)

    def update_confirm_state(self, discovery_id: str, state: dict) -> None:
        """Persist confirm_state JSON and transition status → partial.

        Called after each plan completes so a container restart can resume
        from the last completed plan rather than restarting from scratch.
        """
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    load("update_discovery_confirm_state"),
                    (json.dumps(state), discovery_id),
                )

    def list_recent(self, workspace_id: int, limit: int = 20) -> list[dict[str, Any]]:
        """Return recent discoveries for a workspace, newest first.

        Appends ``pending_days`` ONLY for ``status='pending'`` rows.
        Rows with status ``partial`` (confirm already running) or ``confirmed``
        receive ``pending_days=None`` — the UI only shows the ⚠️ warning for
        genuinely unactioned pending discoveries.
        """
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(load("list_recent_discoveries"), (workspace_id, limit))
                rows = cur.fetchall()

        now = datetime.now(tz=timezone.utc)
        result = []
        for row in rows:
            discovery_id, status, summary_json, file_count, created_at, confirmed_at = row
            summary = json.loads(summary_json or "{}")
            pending_days: int | None = None
            if status == "pending" and created_at is not None:
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=timezone.utc)
                pending_days = (now - created_at).days
            result.append({
                "discovery_id": discovery_id,
                "status":       status,
                "summary":      summary,
                "file_count":   file_count,
                "created_at":   created_at.isoformat() if created_at else None,
                "confirmed_at": confirmed_at.isoformat() if confirmed_at else None,
                "pending_days": pending_days,
            })
        return result

    def close(self) -> None:
        """No-op: connections are managed by the shared pool."""
