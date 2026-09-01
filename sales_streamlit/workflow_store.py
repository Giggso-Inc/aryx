"""PostgreSQL persistence for the Streamlit-owned MSI workflow."""

from __future__ import annotations

from typing import Any

from psycopg.types.json import Json

from aryx.queries import load
from sales_streamlit.msi_workflow import (
    MsiWorkflowRequest,
    new_workflow_record,
)
from aryx.store.pool import get_pool


def _record(row: tuple[Any, ...]) -> dict[str, Any]:
    """Map one SQL result row to the workflow contract."""
    return {
        "workflow_id": str(row[0]),
        "confirmation_id": str(row[1]),
        "actor_id": str(row[2]),
        "thread_id": str(row[3]),
        "status": str(row[4]),
        "current_step": str(row[5] or ""),
        "request": row[6] or {},
        "identifiers": row[7] or {},
        "steps": row[8] or [],
        "error_message": str(row[9] or ""),
        "created_at": row[10],
        "updated_at": row[11],
        "completed_at": row[12],
        "replayed": False,
    }


class SalesMsiWorkflowStore:
    """Durable workflow state keyed by the Aryx confirmation message."""

    def __init__(self, dsn: str) -> None:
        """Acquire the shared PostgreSQL pool for the application DSN."""
        self._pool = get_pool(dsn)

    def close(self) -> None:
        """No-op: shared pool lifecycle is managed globally."""

    def get_by_confirmation(self, confirmation_id: str) -> dict[str, Any] | None:
        """Load the durable workflow for one Aryx confirmation message."""
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(load("select_sales_msi_workflow"), (confirmation_id,))
            row = cur.fetchone()
        return _record(row) if row else None

    def create(self, request: MsiWorkflowRequest) -> dict[str, Any]:
        """Insert an initial workflow or replay a concurrent insert."""
        workflow = new_workflow_record(request)
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                load("insert_sales_msi_workflow"),
                (
                    workflow["workflow_id"],
                    workflow["confirmation_id"],
                    workflow["actor_id"],
                    workflow["thread_id"],
                    workflow["status"],
                    workflow["current_step"],
                    Json(workflow["request"]),
                    Json(workflow["identifiers"]),
                    Json(workflow["steps"]),
                ),
            )
            row = cur.fetchone()
        if row:
            return _record(row)
        existing = self.get_by_confirmation(request.confirmation_id)
        if existing is None:
            raise RuntimeError("Unable to persist MSI workflow")
        existing["replayed"] = True
        return existing

    def save(self, workflow: dict[str, Any]) -> dict[str, Any]:
        """Persist the latest workflow identifiers and step states."""
        error_message = str(workflow.get("error_message") or "")
        if not error_message:
            for step in workflow.get("steps") or []:
                if step.get("status") == "error":
                    error_message = str(step.get("message") or "")
                    break
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                load("update_sales_msi_workflow"),
                (
                    workflow["status"],
                    workflow.get("current_step") or "",
                    Json(workflow.get("identifiers") or {}),
                    Json(workflow.get("steps") or []),
                    error_message[:1000],
                    workflow["status"],
                    workflow["workflow_id"],
                ),
            )
            row = cur.fetchone()
        if row is None:
            raise RuntimeError("MSI workflow disappeared while updating")
        return _record(row)
