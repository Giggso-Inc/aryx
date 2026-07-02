"""DB-backed document-discovery store: replaces the in-memory dict in discoveries.py.

Persists /admin/docs/read results so discoveries survive container restarts and
scale across multiple API instances.  Works on both Postgres and Oracle ADB 23ai
via the shared pool factory — oracle_pool.py handles all SQL translation.
"""
from __future__ import annotations

import base64
import json
import logging
from datetime import datetime, timezone
from typing import Any

from aryx.queries import load
from aryx.store.pool import get_pool

logger = logging.getLogger(__name__)

_COLUMNS = [
    "discovery_id", "workspace_id", "status",
    "data_json", "summary_json", "file_count",
    "confirm_state", "created_at", "confirmed_at",
]

# ── Custom JSON codec for discovery data ─────────────────────────────────────
# data["tabular"][i]["data"] is bytes (raw CSV/JSON file content).
# data["mentions"] is a list of RawRecord Pydantic models.
# Standard json.dumps cannot handle either; these helpers do a lossless
# round-trip so the confirm step receives the same objects it would have
# gotten from the original in-memory dict.

class _DiscoveryEncoder(json.JSONEncoder):
    def default(self, obj: Any) -> Any:
        if isinstance(obj, bytes):
            return {"__b64__": base64.b64encode(obj).decode("ascii")}
        # Pydantic v2 BaseModel — detected by duck-typing to avoid a hard import
        if hasattr(obj, "model_dump") and hasattr(obj, "__class__"):
            return {
                "__pydantic__": type(obj).__qualname__,
                "__module__": type(obj).__module__,
                "v": obj.model_dump(mode="json"),
            }
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


def _discovery_hook(d: dict) -> Any:
    if "__b64__" in d and len(d) == 1:
        return base64.b64decode(d["__b64__"])
    if "__pydantic__" in d:
        cls_name: str = d["__pydantic__"]
        module: str = d.get("__module__", "")
        v: dict = d.get("v", {})
        try:
            import importlib  # noqa: PLC0415
            mod = importlib.import_module(module)
            cls = getattr(mod, cls_name.split(".")[-1])
            return cls.model_validate(v)
        except Exception:  # noqa: BLE001
            return v  # fall back to plain dict if class no longer exists
    return d


def _serialize_data(data: dict) -> str:
    return json.dumps(data, cls=_DiscoveryEncoder)


def _deserialize_data(s: str) -> dict:
    return json.loads(s, object_hook=_discovery_hook)


def _row_to_dict(values: tuple) -> dict[str, Any]:
    row = dict(zip(_COLUMNS, values))
    row["data"]          = _deserialize_data(row.pop("data_json") or "{}")
    row["summary"]       = json.loads(row.pop("summary_json") or "{}")
    row["confirm_state"] = json.loads(row.pop("confirm_state") or "{}")
    return row


class DiscoveryStore:
    """Persists document discoveries (Postgres + Oracle ADB 23ai)."""

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
        params = {
            "discovery_id": discovery_id,
            "workspace_id": workspace_id,
            "data_json":    _serialize_data(data),
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

    def drop(self, discovery_id: str) -> None:
        """Delete a discovery row (no workspace guard — internal cleanup only)."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(load("delete_discovery"), (discovery_id,))

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
