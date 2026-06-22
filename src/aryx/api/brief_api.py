"""Brief drafting API — turn a seed sentence + optional doc text into a brief.

Runs as a durable background job so the HTTP request returns in < 1 second.
This avoids TCP timeouts on slow LLM backends (ECONNRESET in Docker proxies).
The UI polls /admin/jobs/{job_id} and retrieves the brief when done.
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from aryx.api.admin_api import _local_broker
from aryx.brief_draft import draft_from_text
from aryx.config import get_settings
from aryx.store.job_store import JobStore

logger = logging.getLogger(__name__)

# In-memory brief results keyed by job_id.
# Process-local only — sufficient because the UI fetches immediately after
# polling the job to completion within the same session.
_BRIEFS: dict[str, dict[str, Any]] = {}


class DraftBriefRequest(BaseModel):
    """Seed sentence and/or extracted document text to draft a brief from."""

    seed: str = ""
    doc_text: str = ""
    workspace_id: int = 1


def _run_draft(job_id: str, workspace_id: int,
               seed: str, doc_text: str) -> None:
    settings = get_settings()
    jobs = JobStore(settings.rdb_dsn)
    try:
        jobs.update_stage(job_id, "Drafting", 50, "Calling language model…")
        brief = draft_from_text(_local_broker(), seed, doc_text)
        _BRIEFS[job_id] = brief
        jobs.finish(job_id, run_id=None, status="complete")
        logger.info("brief drafted job=%s ws=%s", job_id, workspace_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("brief draft failed job=%s: %s", job_id, exc)
        jobs.finish(job_id, run_id=None, status="failed", error=str(exc))
    finally:
        jobs.close()


def brief_router() -> APIRouter:
    """Build the /admin/workspaces brief-drafting router."""
    router = APIRouter(prefix="/admin/workspaces")

    @router.post("/{workspace_id}/draft-brief")
    def draft_brief(workspace_id: int, req: DraftBriefRequest,
                    background_tasks: BackgroundTasks) -> dict[str, Any]:
        """Start a background brief-draft job; returns job_id immediately."""
        job_id = uuid.uuid4().hex
        settings = get_settings()
        jobs = JobStore(settings.rdb_dsn)
        try:
            jobs.create(job_id, "brief", "drafting brief", workspace_id)
        finally:
            jobs.close()
        background_tasks.add_task(
            _run_draft, job_id, workspace_id, req.seed, req.doc_text,
        )
        return {"job_id": job_id}

    @router.get("/{workspace_id}/brief-result/{job_id}")
    def brief_result(workspace_id: int, job_id: str) -> dict[str, Any]:
        """Retrieve a completed brief draft. 404 while still processing."""
        brief = _BRIEFS.get(job_id)
        if brief is None:
            raise HTTPException(404, "brief not ready or unknown job")
        return {"workspace_id": workspace_id, "brief": brief}

    return router
