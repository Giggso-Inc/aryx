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
import time
import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from aryx import discoveries
from aryx.api.doc_discover.doc_discover_confirm_job import _confirm_job
from aryx.api.doc_discover.doc_discover_read_job import _read_job
from aryx.config import get_settings
from aryx.raven_log import bind_run_id, raven_log, would_log
from aryx.store.discovery_store import DiscoveryStore
from aryx.store.job_store import JobStore

logger = logging.getLogger(__name__)
# Kept in sync with file_ingest_api.py's own _MAX_FILE -- same class of
# upload. Raised once already (to 250 MB, covering a real 223 MB MSI
# catalog export), raised again 2026-09-11 to 500 MB at the operator's
# request. Separate endpoint duplicating the same constant rather than
# sharing it.
_MAX_FILE = 500 * 1024 * 1024


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
        t0 = time.monotonic()
        settings = get_settings()
        items: list[tuple[bytes, str]] = []
        total_bytes = 0
        for f in files:
            data = await f.read()
            if len(data) > _MAX_FILE:
                logger.warning("doc read rejected filename=%s size=%d limit=%d",
                                f.filename, len(data), _MAX_FILE)
                raven_log("WARN", "P3", "ingest.docread.refused file too large", error_code="ARYX_ING_UPLOAD_REFUSED",
                          context={"check": "max_file_bytes", "limit": _MAX_FILE, "measured": len(data),
                                   "decision": "refuse", "reason_code": "FILE_TOO_LARGE"})
                raise HTTPException(
                    400, f"{f.filename}: exceeds {_MAX_FILE // (1024 * 1024)} MB limit",
                )
            items.append((data, f.filename or "upload"))
            total_bytes += len(data)
            if would_log("DEBUG"):
                raven_log("DEBUG", "P4", "ingest.docread.check file accepted",
                          context={"check": "max_file_bytes", "limit": _MAX_FILE, "measured": len(data),
                                   "decision": "pass"})
        did = uuid.uuid4().hex
        jobs = JobStore(settings.effective_dsn())
        try:
            jobs.create(did, "discovery", f"{len(items)} file(s)", workspace_id)
        finally:
            jobs.close()
        logger.info("doc read queued did=%s files=%d workspace_id=%d", did, len(items), workspace_id)
        bind_run_id(did)
        raven_log("INFO", "P4", "ingest.job.queued document read accepted",
                  context={"job_id": did, "discovery_id": did, "workspace_id": workspace_id, "road": "doc_read",
                           "file_count": len(items), "total_bytes": total_bytes,
                           "worker_backend": "background_task", "final_status": "queued", "result": "accepted",
                           "reason_code": "JOB_QUEUED", "duration_ms": int((time.monotonic() - t0) * 1000)})
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
        t0 = time.monotonic()
        # Existence/workspace-ownership check only needs the summary, not the
        # full discovery payload — discoveries.get() would deserialize every
        # raw file's bytes just to answer "does this exist" (confirmed live:
        # 246s for a 257MB discovery). The full get() still happens, just
        # inside _confirm_job()'s background task where it's actually needed.
        if discoveries.get_summary(req.discovery_id, req.workspace_id) is None:
            logger.warning("doc confirm rejected discovery_id=%s: unknown or expired",
                            req.discovery_id)
            raven_log("WARN", "P3", "ingest.docconfirm.refused unknown discovery",
                      error_code="ARYX_ING_CONFIRM_REFUSED",
                      context={"check": "discovery_exists", "discovery_id": req.discovery_id,
                               "workspace_id": req.workspace_id, "decision": "refuse",
                               "reason_code": "UNKNOWN_OR_MISMATCH"})
            raise HTTPException(404, "unknown discovery or workspace mismatch")
        if would_log("DEBUG"):
            raven_log("DEBUG", "P4", "ingest.docconfirm.check discovery found",
                      context={"check": "discovery_exists", "discovery_id": req.discovery_id, "decision": "pass",
                               "restart": req.restart, "approved_types": len(req.approved_types),
                               "approved_files": len(req.approved_files)})
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
        bind_run_id(job_id)
        raven_log("INFO", "P4", "ingest.job.queued document confirm accepted",
                  context={"job_id": job_id, "discovery_id": req.discovery_id, "workspace_id": req.workspace_id,
                           "road": "doc_confirm", "file_count": len(req.approved_files), "total_bytes": 0,
                           "approved_types": len(req.approved_types), "worker_backend": "background_task",
                           "final_status": "queued", "result": "accepted", "reason_code": "JOB_QUEUED",
                           "duration_ms": int((time.monotonic() - t0) * 1000)})
        background_tasks.add_task(_confirm_job, req.discovery_id,
                                  req.approved_types, req.approved_files,
                                  job_id, req.workspace_id, req.restart)
        return {"status": "queued", "job_id": job_id}

    return router
