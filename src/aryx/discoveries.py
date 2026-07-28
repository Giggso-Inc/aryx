"""DB-backed document-discovery store: persists /admin/docs/read results.

Replaces the previous in-memory dict; discoveries now survive container
restarts and work correctly across multiple API instances.
"""
from __future__ import annotations

from typing import Any

from aryx.config import get_settings
from aryx.store.discovery_store import DiscoveryStore


def put(discovery_id: str, data: dict[str, Any], workspace_id: int = 1) -> None:
    """Persist a discovery result."""
    settings = get_settings()
    store = DiscoveryStore(settings.rdb_dsn)
    try:
        summary = data.get("summary", {})
        file_count = (
            len(data.get("tabular", [])) + len(data.get("mentions", []))
        )
        store.put(discovery_id, workspace_id, data, summary, file_count)
    finally:
        store.close()


def get(discovery_id: str, workspace_id: int = 1) -> dict[str, Any] | None:
    """Return a discovery result scoped to the calling workspace, or None."""
    settings = get_settings()
    store = DiscoveryStore(settings.rdb_dsn)
    try:
        row = store.get(discovery_id, workspace_id)
        if not row:
            return None
        data = row["data"]
        if row.get("confirm_state"):
            data["_confirm_state"] = row["confirm_state"]
        return data
    finally:
        store.close()


def get_summary(discovery_id: str, workspace_id: int = 1) -> dict[str, Any] | None:
    """Return just the summary for a discovery, scoped to the calling workspace.

    Cheap path for the review-step UI — see DiscoveryStore.get_summary for why
    the full get() (which deserializes the entire raw-file-bytes payload) is
    unsuitable here.
    """
    settings = get_settings()
    store = DiscoveryStore(settings.rdb_dsn)
    try:
        return store.get_summary(discovery_id, workspace_id)
    finally:
        store.close()


def drop(discovery_id: str) -> None:
    """Delete a discovery result."""
    settings = get_settings()
    store = DiscoveryStore(settings.rdb_dsn)
    try:
        store.drop(discovery_id)
    finally:
        store.close()


def mark_confirmed(discovery_id: str, job_id: str) -> None:
    """Transition a discovery to confirmed status."""
    settings = get_settings()
    store = DiscoveryStore(settings.rdb_dsn)
    try:
        store.mark_confirmed(discovery_id, job_id)
    finally:
        store.close()
