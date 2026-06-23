"""File ingest API: upload up to 50 files (JSON/CSV/PDF/DOCX/PPTX/images).

Limits: 2 MB per file, 50 MB total per request, max 50 files.
JSON/CSV go through the standard entity pipeline.
Documents (PDF/DOCX/PPTX/images) go through chunk→PII→embed→extract→entity.
"""
from __future__ import annotations

import json
import logging
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from aryx.api.admin_api import _local_broker
from aryx.config import get_settings
from aryx.connectors.csv_source import CsvConnector
from aryx.connectors.doc_router import DocumentRouterConnector
from aryx.connectors.json_source import JsonConnector
from aryx.pipeline.orchestrate import run_pipeline
from aryx.store.chunk_store import ChunkStore
from aryx.store.job_store import JobStore
from aryx.store.migrate import apply_migrations

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


_DATA_EXTS = {".json", ".csv"}
_DOC_EXTS = {".pdf", ".pptx", ".ppt", ".docx", ".doc", ".rtf",
             ".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp"}
_ALL = _DATA_EXTS | _DOC_EXTS
_MAX_FILE = 2 * 1024 * 1024
_MAX_TOTAL = 50 * 1024 * 1024
_MAX_FILES = 50


def _save_tmp(data: bytes, suffix: str) -> Path:
    tmp = NamedTemporaryFile(suffix=suffix, delete=False)
    tmp.write(data)
    tmp.close()
    return Path(tmp.name)


def _run_files(items: list[tuple[bytes, str]], ontology_type: str,
               match_keys: list[str], fk_links: list[dict], job_id: str,
               workspace_id: int = 1) -> None:
    settings = get_settings()
    jobs = None
    try:
        jobs = JobStore(settings.rdb_dsn)
        broker = _local_broker()
        data_files = [(d, n) for d, n in items if Path(n).suffix.lower() in _DATA_EXTS]
        doc_files = [(d, n) for d, n in items if Path(n).suffix.lower() in _DOC_EXTS]
        for data, name in data_files:
            suffix = Path(name).suffix.lower()
            if suffix == ".json":
                connector = JsonConnector(_save_tmp(data, ".json"), system="json")
            else:
                connector = CsvConnector(data, system="csv", dataset=Path(name).stem)
            jobs.update_stage(job_id, "Ingest", 20, f"Processing {name}")
            run_pipeline(
                connector=connector, dsn=settings.rdb_dsn,
                system=suffix.lstrip("."), dataset=Path(name).stem,
                ontology_type=ontology_type, match_keys=match_keys,
                graph_url=settings.graph_url, broker=broker,
                on_progress=lambda s, p, d: jobs.update_stage(job_id, s, p, d),
                fk_links=fk_links, workspace_id=workspace_id,
            )
        if doc_files:
            jobs.update_stage(job_id, "Documents", 50, f"Chunking {len(doc_files)} doc(s)")
            paths = [_save_tmp(d, Path(n).suffix) for d, n in doc_files]
            chunk_store = ChunkStore(settings.rdb_dsn)
            connector = DocumentRouterConnector(
                paths=paths, system="document", broker=broker,
                chunk_store=chunk_store, chunk_size=settings.chunk_size,
                chunk_overlap=settings.chunk_overlap, expected_embed_dim=settings.embed_dim,
            )
            run_pipeline(
                connector=connector, dsn=settings.rdb_dsn,
                system="document", dataset="upload",
                ontology_type=ontology_type, match_keys=match_keys,
                graph_url=settings.graph_url, broker=broker,
                on_progress=lambda s, p, d: jobs.update_stage(job_id, s, p, d),
                fk_links=fk_links, workspace_id=workspace_id,
            )
        jobs.finish(job_id, run_id=None, status="complete")
    except Exception as exc:  # noqa: BLE001
        logger.warning("file ingest failed job=%s: %s", job_id, exc)
        if jobs is not None:
            jobs.finish(job_id, run_id=None, status="failed", error=str(exc))
    finally:
        if jobs is not None:
            jobs.close()


def file_ingest_router() -> APIRouter:
    router = APIRouter(prefix="/admin")

    @router.post("/ingest/file")
    async def ingest_file(
        files: list[UploadFile] = File(...),
        ontology_type: str = Form(...),
        match_keys: str = Form(...),
        fk_links: str = Form("[]"),
        workspace_id: int = Form(1),
    ) -> dict[str, Any]:
        if len(files) > _MAX_FILES:
            raise HTTPException(400, f"Max {_MAX_FILES} files per upload")
        items: list[tuple[bytes, str]] = []
        total = 0
        for f in files:
            data = await f.read()
            if len(data) > _MAX_FILE:
                raise HTTPException(400, f"{f.filename}: exceeds 2 MB limit")
            total += len(data)
            if total > _MAX_TOTAL:
                raise HTTPException(400, f"Total upload exceeds 50 MB limit")
            suffix = Path(f.filename or "").suffix.lower()
            if suffix not in _ALL:
                raise HTTPException(400, f"{f.filename}: unsupported type {suffix}")
            items.append((data, f.filename or f"upload{suffix}"))
        settings = get_settings()
        apply_migrations(settings.rdb_dsn)
        job_id = uuid.uuid4().hex
        jobs = JobStore(settings.rdb_dsn)
        try:
            jobs.create(job_id, "upload", f"{len(items)} file(s)", workspace_id)
        finally:
            jobs.close()
        keys = [k.strip() for k in match_keys.split(",") if k.strip()]
        links = json.loads(fk_links) if fk_links else []
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
                    "dsn": settings.rdb_dsn,
                    "graph_url": settings.graph_url,
                    "chunk_size": settings.chunk_size,
                    "chunk_overlap": settings.chunk_overlap,
                    "embed_dim": settings.embed_dim,
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
            future = _get_executor().submit(_run_files, items, ontology_type, keys, links, job_id, workspace_id)
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
                "max_file_mb": 2, "max_total_mb": 50}

    return router
