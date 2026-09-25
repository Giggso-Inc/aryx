"""Observability API: single endpoint for the dashboard panel.

Aggregates: job pipeline health, LLM token/latency usage, graph entity/edge
counts, and model config — everything the UI needs in one call.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from aryx.llm import llm_runtime
from aryx.config import get_settings
from aryx.ports import ports
from aryx.queries import load
from aryx.store.pool import get_pool


def _job_summary(conn: Any, workspace_id: int) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(load("select_job_summary"), (workspace_id,))
        by_status = {r[0]: r[1] for r in cur.fetchall()}
        cur.execute(load("select_job_total"), (workspace_id,))
        total = cur.fetchone()[0]
    return {"total": total, **by_status}


def _llm_stats(conn: Any, workspace_id: int) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(load("select_llm_stats"), (workspace_id,))
        row = cur.fetchone()
    if not row:
        return {}
    return {"total_calls": row[0], "total_tokens": row[1],
            "avg_latency_ms": row[2], "prompt_tokens": row[3],
            "completion_tokens": row[4]}


def _recent_llm(conn: Any, workspace_id: int) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(load("select_recent_llm_calls"), (workspace_id,))
        cols = ["role", "model", "prompt_tokens", "completion_tokens",
                "latency_ms", "source", "error", "ts"]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def _graph_stats(workspace_id: int) -> dict[str, int]:
    # CPQ_Hardcode_Audit_dev_oci_2026-09-25.md T11: len(find_entities(limit=500))
    # silently capped the dashboard's entity count at 500 regardless of the
    # workspace's real size. count_entities() is a true, uncapped count.
    try:
        reader = ports().graph_reader(workspace_id)
        return {"entities": reader.count_entities(),
                "relationships": len(reader.all_relationships())}
    except Exception:
        return {"entities": 0, "relationships": 0}


def observability_router() -> APIRouter:
    router = APIRouter(prefix="/admin")

    @router.get("/observability")
    def observability(workspace_id: int = 1) -> dict[str, Any]:
        with get_pool(get_settings().effective_dsn()).connection() as conn:
            return {
                "jobs": _job_summary(conn, workspace_id),
                "llm": _llm_stats(conn, workspace_id),
                "llm_recent": _recent_llm(conn, workspace_id),
                "graph": _graph_stats(workspace_id),
                "model_config": llm_runtime.status(),
                "platform": ports().describe(),
            }

    return router
