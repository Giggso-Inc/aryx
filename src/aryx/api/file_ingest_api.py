"""File ingest API: upload files (JSON/CSV/XML/XLSX/PDF/DOCX/PPTX/HTML/images).

Limits are runtime-configurable — see Settings.max_upload_file_mb /
max_upload_total_mb / max_upload_files (ARYX_MAX_UPLOAD_* env vars) — not
hardcoded, so a deployment can raise them without a code change or rebuild.
JSON/CSV/XML/XLSX go through the standard entity pipeline.
Documents (PDF/DOCX/PPTX/HTML/images) go through chunk→PII→embed→extract→entity.

Ingest jobs run on a bounded ``ThreadPoolExecutor`` (sized by
``settings.worker_threads``) rather than FastAPI's single-shot
``BackgroundTasks`` runner, so multiple large uploads (e.g. several big
workbooks or a 1000+-page PDF) can make progress concurrently instead of
queuing behind each other.
"""
from __future__ import annotations

import csv
import io
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
from aryx.pipeline.doc_discovery import _chunk_csv_bytes, _infer_type, expand_data_files, infer_fk_links
from aryx.pipeline.dynamic_fk import detect_dynamic_fk_links
from aryx.pipeline.orchestrate import link_entities, relate_isolated, run_pipeline
from aryx.store.chunk_store import ChunkStore
from aryx.store.job_store import JobStore
from aryx.store.migrate import apply_migrations

logger = logging.getLogger(__name__)

_DATA_EXTS = {".json", ".csv", ".xlsx", ".xml"}
_DOC_EXTS = {".pdf", ".pptx", ".ppt", ".docx", ".doc", ".rtf", ".html", ".htm",
             ".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp"}
_ALL = _DATA_EXTS | _DOC_EXTS

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
    so job records are never left in a partial state.
    """
    global _executor
    with _executor_lock:
        if _executor is not None:
            _executor.shutdown(wait=True)
            _executor = None


def _save_tmp(data: bytes, suffix: str) -> Path:
    tmp = NamedTemporaryFile(suffix=suffix, delete=False)
    tmp.write(data)
    tmp.close()
    return Path(tmp.name)


def _colvals(data: bytes, suffix: str) -> dict[str, Any]:
    """Return {colvals: {column -> [values]}} for FK discovery ({} on failure)."""
    if suffix == ".json":
        return {"colvals": {}}
    try:
        reader = csv.DictReader(io.StringIO(data.decode("utf-8", "ignore")))
        cols: dict[str, list[str]] = {}
        for row in reader:
            for k, v in row.items():
                if k is not None:
                    cols.setdefault(k, []).append((v or "").strip())
        return {"colvals": cols}
    except csv.Error:
        return {"colvals": {}}


def _run_files(items: list[tuple[bytes, str]], ontology_type: str,
               match_keys: list[str], fk_links: list[dict], job_id: str,
               workspace_id: int = 1) -> None:
    settings = get_settings()
    jobs = JobStore(settings.rdb_dsn)
    broker = _local_broker()
    try:
        # Every .xlsx sheet / .xml entity type becomes its own CSV "file" —
        # the rest of the pipeline (type inference, cross-file FK linking,
        # run_pipeline) doesn't need to know a workbook or XML doc was
        # involved. This flattening happens across ALL uploaded files up
        # front, so the FK-inference pass below already sees every sheet
        # from every workbook (and every XML-derived table) together — links
        # between two separately-uploaded files are found, not just within
        # one workbook.
        items = expand_data_files(items)
        data_files = [(d, n) for d, n in items if Path(n).suffix.lower() in _DATA_EXTS]
        doc_files = [(d, n) for d, n in items if Path(n).suffix.lower() in _DOC_EXTS]
        # Per-file plans feed cross-file FK inference once everything has landed.
        plans: list[dict[str, Any]] = []
        for data, name in data_files:
            suffix = Path(name).suffix.lower()
            # Per-file type/key inference. A single (type, match_keys) pair
            # cannot fit a heterogeneous batch of files, and the UI default
            # ("Document" / "name") matches no real CSV column — which yields
            # empty match text and collapses every row into one entity. When
            # the caller didn't pin a concrete type, infer the row entity and
            # its identifying columns from this file's own header + sample.
            otype, keys = ontology_type, match_keys
            if not otype or otype.lower() == "document":
                plan = _infer_type(data[:800].decode("utf-8", "ignore"), name, "")
                otype, keys = plan["ontology_type"], plan["match_keys"]
                logger.info("inferred %s -> type=%s keys=%s", name, otype, keys)
            cv = _colvals(data, suffix)
            # Validate match keys against real columns. A bogus key (the LLM
            # invents one, or wrong casing) forces the whole-row fallback in
            # landed_records — which makes every row's match text huge and
            # similar, exploding pairwise scoring + adjudication into hours.
            # Repair deterministically: use the most-unique column (the natural
            # key) so matching is both fast and correct.
            cols = list(cv["colvals"].keys())
            valid = [k for k in keys if k in cols]
            if valid:
                keys = valid
            elif cols:
                best = max(cols, key=lambda c: len({v for v in cv["colvals"][c] if v}))
                logger.info("match_keys %s not columns of %s; using key '%s'",
                            keys, name, best)
                keys = [best]
            plans.append({"ontology_type": otype, **cv})
            jobs.update_stage(job_id, "Ingest", 20, f"Processing {name}")
            # Large sheets/files are split into row-bounded chunks so a
            # single huge workbook sheet doesn't hold the whole pipeline run
            # (and its memory) in one shot. Disabled by default
            # (ARYX_CSV_CHUNK_ROWS=0); each chunk shares the same inferred
            # type/keys so they land as one logical dataset.
            for chunk in _chunk_csv_bytes(data, settings.csv_chunk_rows) if suffix == ".csv" else [data]:
                if suffix == ".json":
                    connector = JsonConnector(_save_tmp(chunk, ".json"), system="json")
                else:
                    connector = CsvConnector(chunk, system="csv", dataset=Path(name).stem)
                run_pipeline(
                    connector=connector, dsn=settings.rdb_dsn,
                    system=suffix.lstrip("."), dataset=Path(name).stem,
                    ontology_type=otype, match_keys=keys,
                    graph_url=settings.graph_url, broker=broker,
                    on_progress=lambda s, p, d: jobs.update_stage(job_id, s, p, d),
                    fk_links=fk_links, workspace_id=workspace_id,
                )
        # Cross-file relationships. The UI sends no fk_links, so with every
        # entity now landed, infer foreign-key edges from the files' columns
        # and materialize the ones whose values actually match, then re-project.
        if not fk_links and len(plans) >= 2:
            jobs.update_stage(job_id, "Link", 92, "Inferring relationships")
            inferred = infer_fk_links(plans)
            # Column-name matching (above) only catches FK-shaped names like
            # `CustomerID`. Value-overlap detection catches the rest — two
            # columns with different names whose *values* line up (common
            # across independently-authored Excel workbooks).
            already = {(l["source_type"], l["source_attr"], l["target_type"], l["target_attr"]) for l in inferred}
            inferred += [
                l for l in detect_dynamic_fk_links(plans)
                if (l["source_type"], l["source_attr"], l["target_type"], l["target_attr"]) not in already
            ]
            if inferred:
                link_entities(settings.rdb_dsn, settings.graph_url,
                              workspace_id, inferred)
        if doc_files:
            jobs.update_stage(job_id, "Documents", 50, f"Chunking {len(doc_files)} doc(s)")
            paths = [_save_tmp(d, Path(n).suffix) for d, n in doc_files]
            chunk_store = ChunkStore(settings.rdb_dsn)
            # Real chunk-based progress instead of a static 50% for however
            # long extraction takes on a large document.
            def _on_extract_progress(completed: int, total: int, _new: list) -> None:
                pct = 50 + int(min(completed / max(total, 1), 1.0) * 40)
                jobs.update_stage(job_id, "Documents", min(pct, 90),
                                  f"Extracted {completed}/{total} chunk(s)…")
            connector = DocumentRouterConnector(
                paths=paths, system="document", broker=broker,
                chunk_store=chunk_store, chunk_size=settings.chunk_size,
                chunk_overlap=settings.chunk_overlap, expected_embed_dim=settings.embed_dim,
                on_progress=_on_extract_progress,
            )
            run_pipeline(
                connector=connector, dsn=settings.rdb_dsn,
                system="document", dataset="upload",
                ontology_type=ontology_type, match_keys=match_keys,
                graph_url=settings.graph_url, broker=broker,
                on_progress=lambda s, p, d: jobs.update_stage(job_id, s, p, d),
                fk_links=fk_links, workspace_id=workspace_id,
            )
        # Deliberately unconditional — guarantees no entity from this batch
        # (tabular or document-extracted) is left with zero relationships,
        # regardless of whether relate/FK-linking above found anything.
        if data_files or doc_files:
            jobs.update_stage(job_id, "Link", 95, "Checking for isolated entities")
            relate_isolated(settings.rdb_dsn, settings.graph_url, workspace_id, broker)
        jobs.finish(job_id, run_id=None, status="complete")
    except Exception as exc:  # noqa: BLE001
        logger.warning("file ingest failed job=%s: %s", job_id, exc, exc_info=True)
        jobs.finish(job_id, run_id=None, status="failed", error=str(exc))
    finally:
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
        settings = get_settings()
        max_file = settings.max_upload_file_mb * 1024 * 1024
        max_total = settings.max_upload_total_mb * 1024 * 1024
        if len(files) > settings.max_upload_files:
            raise HTTPException(400, f"Max {settings.max_upload_files} files per upload")
        items: list[tuple[bytes, str]] = []
        total = 0
        for f in files:
            data = await f.read()
            if len(data) > max_file:
                raise HTTPException(400, f"{f.filename}: exceeds {settings.max_upload_file_mb} MB limit")
            total += len(data)
            if total > max_total:
                raise HTTPException(400, f"Total upload exceeds {settings.max_upload_total_mb} MB limit")
            suffix = Path(f.filename or "").suffix.lower()
            if suffix not in _ALL:
                raise HTTPException(400, f"{f.filename}: unsupported type {suffix}")
            items.append((data, f.filename or f"upload{suffix}"))
        apply_migrations(settings.rdb_dsn)
        job_id = uuid.uuid4().hex
        jobs = JobStore(settings.rdb_dsn)
        try:
            jobs.create(job_id, "upload", f"{len(items)} file(s)", workspace_id)
        finally:
            jobs.close()
        keys = [k.strip() for k in match_keys.split(",") if k.strip()]
        links = json.loads(fk_links) if fk_links else []

        def _on_done(fut) -> None:
            exc = fut.exception()
            if exc is not None:
                logger.error("ingest job %s crashed outside its own handler: %s", job_id, exc, exc_info=exc)

        future = _get_executor().submit(_run_files, items, ontology_type, keys, links, job_id, workspace_id)
        future.add_done_callback(_on_done)
        names = [n for _, n in items]
        return {"status": "queued", "job_id": job_id, "files": names, "count": len(items)}

    @router.get("/ingest/supported")
    def supported_types() -> dict[str, Any]:
        settings = get_settings()
        return {
            "file_types": sorted(_ALL),
            "max_files": settings.max_upload_files,
            "max_file_mb": settings.max_upload_file_mb,
            "max_total_mb": settings.max_upload_total_mb,
        }

    return router
