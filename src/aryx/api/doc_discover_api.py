"""Document self-discovery API: read → summary → confirm (no ontology input).

The user just uploads files. Reading discovers entity types from content; the
summary is reviewed; confirm ingests only the approved types. Reading and
ingesting both run as durable jobs so the UI can show live progress.

As of the Raven Style Compliance Plan's Phase 2b (2026-09-03), split into
`doc_discover_read_job.py` (`_save_tmp`/`_build_read_progress`/`_read_job`)
and `doc_discover_confirm_job.py` (`_reset_discovery_status`/`_confirm_job`),
both re-imported here. Zero whitebox test patches exist anywhere against
`aryx.api.doc_discover_api.*` (confirmed via grep), so the split was
purely mechanical. `doc_discover_router` — wiring the routes to the
background jobs — stays here.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from aryx import discoveries
from aryx.api.doc_discover_confirm_job import _confirm_job
from aryx.api.doc_discover_read_job import _read_job
from aryx.config import get_settings
from aryx.store.discovery_store import DiscoveryStore
from aryx.store.job_store import JobStore

logger = logging.getLogger(__name__)
_MAX_FILE = 50 * 1024 * 1024


class ConfirmRequest(BaseModel):
    discovery_id: str
    approved_types: list[str] = []
    approved_files: list[str] = []
    workspace_id: int = 1
    resume_job_id: str | None = None
    restart: bool = False


def doc_discover_router() -> APIRouter:
    router = APIRouter(prefix="/admin/docs")

    @router.post("/read")
    async def read(background_tasks: BackgroundTasks,
                   files: list[UploadFile] = File(...), context: str = Form(""),
                   workspace_id: int = Form(1)) -> dict[str, Any]:
        settings = get_settings()
        items: list[tuple[bytes, str]] = []
        for f in files:
            data = await f.read()
            if len(data) > _MAX_FILE:
                logger.warning("doc read rejected filename=%s size=%d limit=%d",
                                f.filename, len(data), _MAX_FILE)
                raise HTTPException(400, f"{f.filename}: exceeds 50 MB limit")
            items.append((data, f.filename or "upload"))
        did = uuid.uuid4().hex
        jobs = JobStore(settings.effective_dsn())
        try:
            jobs.create(did, "discovery", f"{len(items)} file(s)", workspace_id)
        finally:
            jobs.close()
        logger.info("doc read queued did=%s files=%d workspace_id=%d", did, len(items), workspace_id)
        background_tasks.add_task(_read_job, items, context, did, workspace_id)
        return {"discovery_id": did}

    @router.get("/summary/{did}")
    def summary(did: str, workspace_id: int = 1) -> dict[str, Any]:
        result = discoveries.get_summary(did, workspace_id)
        return result if result is not None else {}

    @router.get("/history")
    def history(workspace_id: int = 1) -> list[dict[str, Any]]:
        settings = get_settings()
        store = DiscoveryStore(settings.effective_dsn())
        try:
            return store.list_recent(workspace_id)
        finally:
            store.close()

    @router.post("/confirm")
    def confirm(req: ConfirmRequest, background_tasks: BackgroundTasks) -> dict[str, Any]:
        # Existence/workspace-ownership check only needs the summary, not the
        # full discovery payload — discoveries.get() would deserialize every
        # raw file's bytes just to answer "does this exist" (confirmed live:
        # 246s for a 257MB discovery). The full get() still happens, just
        # inside _confirm_job()'s background task where it's actually needed.
        if discoveries.get_summary(req.discovery_id, req.workspace_id) is None:
            logger.warning("doc confirm rejected discovery_id=%s: unknown or expired",
                            req.discovery_id)
            raise HTTPException(404, "unknown discovery or workspace mismatch")
        job_id = uuid.uuid4().hex
        jobs = JobStore(get_settings().effective_dsn())
        try:
            jobs.create(job_id, "documents", "confirmed entities", req.workspace_id)
        finally:
            jobs.close()
        disc_store = DiscoveryStore(get_settings().effective_dsn())
        try:
            disc_store.set_status(req.discovery_id, "confirming")
        finally:
            disc_store.close()
        logger.info("doc confirm queued did=%s job=%s types=%d files=%d workspace_id=%d",
                    req.discovery_id, job_id, len(req.approved_types), len(req.approved_files),
                    req.workspace_id)
        background_tasks.add_task(_confirm_job, req.discovery_id,
                                  req.approved_types, req.approved_files,
                                  job_id, req.workspace_id, req.restart)
        return {"status": "queued", "job_id": job_id}

    return router
