"""File ingest API: upload up to 50 files (JSON/CSV/PDF/DOCX/PPTX/images).

Limits: 500 MB per file, 1500 MB total per request, max 50 files.
JSON/CSV go through the standard entity pipeline.
Documents (PDF/DOCX/PPTX/images) go through chunk→PII→embed→extract→entity.

As of the Raven Style Compliance Plan's Phase 2a (2026-09-03), the size/type
limits live in `api.file_ingest_limits` and the background worker
(`_run_files` + its helpers `_save_tmp`/`_chunk_csv_bytes`/`_make_should_stop`)
lives in `api.file_ingest_run` -- both re-imported here so `main.py`'s
existing import, `_run_files`'s external callers, and direct imports of the
helpers keep working unchanged. Whitebox patches on `_run_files`'s OWN
internal dependencies (DatasourceStore, JobStore, run_pipeline, etc.) were
retargeted to `aryx.api.file_ingest.file_ingest_run.*` in the affected tests, since those
calls now resolve via that module's namespace, not this one. The executor
singleton (`_get_executor`/`shutdown_executor`) stays in this module because
its own `get_settings()` call is patched via THIS module's namespace in
`test_scalability_fixes.py`, and moving it would gain only ~25 lines.
"""
from __future__ import annotations

import json
import logging
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from aryx.api.file_ingest.file_ingest_limits import _ALL, _FK_REQUIRED_KEYS, _MAX_FILE, _MAX_FILES, _MAX_TOTAL
from aryx.api.file_ingest.file_ingest_run import _chunk_csv_bytes, _make_should_stop, _run_files, _save_tmp
from aryx.config import get_settings
from aryx.store.job_store import JobStore

__all__ = [
    "_chunk_csv_bytes",
    "_get_executor",
    "_make_should_stop",
    "_run_files",
    "_save_tmp",
    "file_ingest_router",
    "shutdown_executor",
]

logger = logging.getLogger(__name__)

_executor: ThreadPoolExecutor | None = None
_executor_lock = threading.Lock()


def _get_executor() -> ThreadPoolExecutor:
    """Return the module-level ingest executor, creating it on first call."""
    global _executor
    with _executor_lock:
        if _executor is None:
            _executor = ThreadPoolExecutor(max_workers=get_settings().worker_threads)
    return _executor


def shutdown_executor() -> None:
    """Drain the ingest executor — call from the app lifespan on shutdown.

    Waits for all in-flight ingest jobs to complete before the process exits
    so that job records are not left in a partial state.
    """
    global _executor
    with _executor_lock:
        if _executor is not None:
            _executor.shutdown(wait=True)
            _executor = None


def file_ingest_router() -> APIRouter:
    router = APIRouter(prefix="/admin")

    @router.post("/ingest/file")
    async def ingest_file(
        files: list[UploadFile] = File(...),
        ontology_type: str = Form(...),
        match_keys: str = Form(...),
        fk_links: str = Form("[]"),
        workspace_id: int = Form(1),
        catalog_prefix: str | None = Form(
            None,
            description=(
                "CPQ_LAYOUT_FILE_STORAGE_MIGRATION_PLAN_2026-09-30.md: "
                "explicit catalog_prefix for any .txt/.json layout-export "
                "file(s) in this batch (only takes effect when "
                "ARYX_INGEST_PIPELINE and ARYX_CPQ_LAYOUT_SOURCE are both "
                "set). Omitted -> falls back to the filename-derived stem, "
                "as before. Applied to every layout file in the batch if "
                "more than one is uploaded in the same request."
            ),
        ),
    ) -> dict[str, Any]:
        if len(files) > _MAX_FILES:
            raise HTTPException(400, f"Max {_MAX_FILES} files per upload")
        items: list[tuple[bytes, str]] = []
        total = 0
        for f in files:
            data = await f.read()
            if len(data) > _MAX_FILE:
                raise HTTPException(
                    400, f"{f.filename}: exceeds {_MAX_FILE // (1024 * 1024)} MB limit",
                )
            total += len(data)
            if total > _MAX_TOTAL:
                raise HTTPException(
                    400, f"Total upload exceeds {_MAX_TOTAL // (1024 * 1024)} MB limit",
                )
            suffix = Path(f.filename or "").suffix.lower()
            if suffix not in _ALL:
                raise HTTPException(400, f"{f.filename}: unsupported type {suffix}")
            items.append((data, f.filename or f"upload{suffix}"))
        settings = get_settings()
        job_id = uuid.uuid4().hex
        jobs = JobStore(settings.effective_dsn())
        try:
            jobs.create(job_id, "upload", f"{len(items)} file(s)", workspace_id)
        finally:
            jobs.close()
        keys = [k.strip() for k in match_keys.split(",") if k.strip()]

        try:
            links = json.loads(fk_links) if fk_links else []
        except json.JSONDecodeError as exc:
            raise HTTPException(400, f"fk_links is not valid JSON: {exc}") from exc
        worker_backend = settings.effective_worker_backend()
        if worker_backend == "oci_functions":
            import base64
            from aryx.worker.oci_functions_worker import submit_to_oci_function
            for file_bytes, filename in items:
                payload = {
                    "job_id": job_id,
                    "workspace_id": workspace_id,
                    "ontology_type": ontology_type,
                    "match_keys": keys,
                    "fk_links": links,
                    "filename": filename,
                    "file_b64": base64.b64encode(file_bytes).decode(),
                }
                submit_to_oci_function(settings.oci_ingest_fn_id, payload)
        elif worker_backend == "oci_dataflow":
            from aryx.worker.oci_dataflow_worker import submit_to_dataflow
            submit_to_dataflow(
                settings.oci_dataflow_app_id,
                args=["--job-id", job_id, "--workspace-id", str(workspace_id),
                      "--ontology-type", ontology_type],
                display_name=f"aryx-ingest-{job_id[:8]}",
            )
        else:
            for i, lnk in enumerate(links):
                if not isinstance(lnk, dict) or not _FK_REQUIRED_KEYS.issubset(lnk):
                    raise HTTPException(400,
                        f"fk_links[{i}] missing required keys: {sorted(_FK_REQUIRED_KEYS)}")
            future = _get_executor().submit(
                _run_files, items, ontology_type, keys, links, job_id, workspace_id,
                catalog_prefix,
            )
            future.add_done_callback(
                lambda f: (exc := f.exception()) and logger.error(
                    "ingest job=%s raised unhandled exception: %s", job_id, exc
                )
            )
        names = [n for _, n in items]
        return {"status": "queued", "job_id": job_id, "files": names, "count": len(items)}

    @router.get("/ingest/supported")
    def supported_types() -> dict[str, Any]:
        return {"file_types": sorted(_ALL), "max_files": _MAX_FILES,
                "max_file_mb": _MAX_FILE // (1024 * 1024),
                "max_total_mb": _MAX_TOTAL // (1024 * 1024)}

    return router
