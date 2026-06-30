"""File ingest API: upload up to 50 files (JSON/CSV/PDF/DOCX/PPTX/images).

Limits: 2 MB per file, 50 MB total per request, max 50 files.
JSON/CSV go through the standard entity pipeline.
Documents (PDF/DOCX/PPTX/images) go through chunk→PII→embed→extract→entity.
"""
from __future__ import annotations

import csv as _csv
import io
import itertools
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
from aryx.pipeline.doc_discovery import _detect_fk_links, _stem_type, _xml_to_csvs
from aryx.pipeline.orchestrate import run_pipeline
from aryx.store.chunk_store import ChunkStore
from aryx.store.job_store import JobStore
from aryx.store.migrate import apply_migrations

logger = logging.getLogger(__name__)

_executor: ThreadPoolExecutor | None = None
_executor_lock = threading.Lock()


def _get_executor() -> ThreadPoolExecutor:
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


_DATA_EXTS = {".json", ".csv", ".xml"}
_DOC_EXTS = {".pdf", ".pptx", ".ppt", ".docx", ".doc", ".rtf",
             ".html", ".htm",
             ".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp"}
_ALL = _DATA_EXTS | _DOC_EXTS
_MAX_FILE = 50 * 1024 * 1024
_MAX_TOTAL = 500 * 1024 * 1024
_MAX_FILES = 50


def _save_tmp(data: bytes, suffix: str) -> Path:
    tmp = NamedTemporaryFile(suffix=suffix, delete=False)
    tmp.write(data)
    tmp.close()
    return Path(tmp.name)


_FK_REQUIRED_KEYS = frozenset({"source_type", "target_type", "source_attr", "target_attr"})


def _chunk_csv_bytes(data: bytes, chunk_rows: int) -> list[bytes]:
    """Split CSV bytes into chunks of at most chunk_rows data rows, repeating the header.

    Streams rows via itertools.islice so the full file is never materialised
    into a list — only one batch is held in memory at a time.
    """
    reader = _csv.reader(io.StringIO(data.decode("utf-8")))
    try:
        header = next(reader)
    except StopIteration:
        return [data]
    chunks: list[bytes] = []
    while True:
        batch = list(itertools.islice(reader, chunk_rows))
        if not batch:
            break
        buf = io.StringIO()
        writer = _csv.writer(buf)
        writer.writerow(header)
        writer.writerows(batch)
        chunks.append(buf.getvalue().encode("utf-8"))
    return chunks or [data]


def _run_files(items: list[tuple[bytes, str]], ontology_type: str,
               match_keys: list[str], fk_links: list[dict], job_id: str,
               workspace_id: int = 1) -> None:
    settings = get_settings()
    jobs: JobStore | None = None
    tmp_paths: list[Path] = []
    try:
        jobs = JobStore(settings.rdb_dsn)
        on_prog = lambda s, p, d: jobs.update_stage(job_id, s, p, d)
        broker = _local_broker()
        data_files = [(d, n) for d, n in items if Path(n).suffix.lower() in _DATA_EXTS]
        doc_files = [(d, n) for d, n in items if Path(n).suffix.lower() in _DOC_EXTS]

        # Pre-compute FK links for multi-file CSV uploads so that cross-file
        # relationships are detected before any pipeline runs (mirrors XML path).
        csv_data_files = [(d, n) for d, n in data_files if Path(n).suffix.lower() == ".csv"]
        csv_auto_fk: list[dict] = []
        csv_type_map: dict[str, str] = {}  # filename -> derived ontology type
        if len(csv_data_files) > 1:
            csv_plans = []
            for csv_d, csv_n in csv_data_files:
                derived = _stem_type(csv_n) or ontology_type
                csv_type_map[csv_n] = derived
                csv_plans.append({
                    "data": csv_d,
                    "filename": csv_n,
                    "ontology_type": derived,
                    "match_keys": match_keys or ["name"],
                })
            csv_auto_fk = _detect_fk_links(csv_plans)
            if csv_auto_fk:
                logger.info(
                    "CSV multi-file: auto-detected %d fk-link spec(s): %s",
                    len(csv_auto_fk), csv_auto_fk,
                )

        for data, name in data_files:
            suffix = Path(name).suffix.lower()
            if suffix == ".json":
                tmp = _save_tmp(data, ".json")
                tmp_paths.append(tmp)
                jobs.update_stage(job_id, "Ingest", 20, f"Processing {name}")
                run_pipeline(
                    connector=JsonConnector(tmp, system="json"),
                    dsn=settings.rdb_dsn,
                    system="json", dataset=Path(name).stem,
                    ontology_type=ontology_type, match_keys=match_keys,
                    graph_url=settings.graph_url, broker=broker,
                    on_progress=on_prog,
                    fk_links=fk_links, workspace_id=workspace_id,
                    relate=True,
                )
            elif suffix == ".xml":
                # Expand XML into one connector per top-3 element type.
                # Each CSV gets its own ontology_type derived from the element
                # tag so that cross-type pairs are generated for relate/fk_link.
                orig_stem = Path(name).stem
                xml_csvs = _xml_to_csvs(data, orig_stem)
                xml_plans = []
                for csv_data, csv_name in xml_csvs:
                    csv_stem = Path(csv_name).stem
                    # csv_name == "{orig_stem}_{tag}.csv" — strip the prefix to get the tag.
                    tag = csv_stem[len(orig_stem) + 1:] if csv_stem.startswith(orig_stem + "_") else csv_stem
                    derived_type = "".join(w.title() for w in tag.split("_") if w) or ontology_type
                    xml_plans.append((csv_data, csv_name, derived_type))
                # Auto-detect FK links now that all element types are known.
                fk_plan_dicts = [
                    {"data": d, "filename": n, "ontology_type": t, "match_keys": match_keys or ["name"]}
                    for d, n, t in xml_plans
                ]
                auto_fk = _detect_fk_links(fk_plan_dicts)
                if auto_fk:
                    logger.info("XML auto-detected %d fk-link spec(s): %s", len(auto_fk), auto_fk)
                for idx, (csv_data, csv_name, derived_type) in enumerate(xml_plans):
                    is_last = (idx == len(xml_plans) - 1)
                    jobs.update_stage(job_id, "Ingest", 20, f"Processing {csv_name}")
                    # relate=False on all sub-pipelines except the last so that the
                    # LLM relationship pass runs once across the full merged entity set
                    # instead of N times on incomplete per-type slices (N×10 → 10 calls).
                    run_pipeline(
                        connector=CsvConnector(csv_data, system="csv",
                                               dataset=Path(csv_name).stem),
                        dsn=settings.rdb_dsn,
                        system="csv", dataset=Path(csv_name).stem,
                        ontology_type=derived_type, match_keys=match_keys,
                        graph_url=settings.graph_url, broker=broker,
                        on_progress=on_prog,
                        fk_links=auto_fk if is_last else [],
                        workspace_id=workspace_id,
                        relate=is_last,
                    )
                continue
            else:
                # Multi-file CSV: derive type per filename and apply auto FK links
                # on the last file's last chunk (same pattern as XML sub-pipeline).
                # Single-file CSV: preserve user-provided ontology_type and fk_links.
                multi_csv = len(csv_data_files) > 1
                is_last_csv = multi_csv and (name == csv_data_files[-1][1])
                eff_type = csv_type_map.get(name, ontology_type) if multi_csv else ontology_type
                eff_fk = csv_auto_fk if is_last_csv else (fk_links if not multi_csv else [])
                eff_relate = is_last_csv if multi_csv else True

                chunk_rows = settings.csv_chunk_rows
                csv_chunks = _chunk_csv_bytes(data, chunk_rows) if chunk_rows > 0 else [data]
                stem = Path(name).stem
                total_chunks = len(csv_chunks)
                for chunk_idx, chunk_data in enumerate(csv_chunks):
                    is_last_chunk = (chunk_idx == total_chunks - 1)
                    dataset = f"{stem}_c{chunk_idx:04d}" if total_chunks > 1 else stem
                    jobs.update_stage(
                        job_id, "Ingest", 20,
                        f"Processing {name}" + (f" chunk {chunk_idx + 1}/{total_chunks}" if total_chunks > 1 else ""),
                    )
                    run_pipeline(
                        connector=CsvConnector(chunk_data, system="csv", dataset=dataset),
                        dsn=settings.rdb_dsn,
                        system="csv", dataset=dataset,
                        ontology_type=eff_type, match_keys=match_keys,
                        graph_url=settings.graph_url, broker=broker,
                        on_progress=on_prog,
                        fk_links=eff_fk if is_last_chunk else [],
                        workspace_id=workspace_id,
                        relate=eff_relate and is_last_chunk,
                    )
        if doc_files:
            jobs.update_stage(job_id, "Documents", 50, f"Chunking {len(doc_files)} doc(s)")
            doc_paths = [_save_tmp(d, Path(n).suffix) for d, n in doc_files]
            tmp_paths.extend(doc_paths)
            chunk_store = ChunkStore(settings.rdb_dsn)
            connector = DocumentRouterConnector(
                paths=doc_paths, system="document", broker=broker,
                chunk_store=chunk_store, chunk_size=settings.chunk_size,
                chunk_overlap=settings.chunk_overlap, expected_embed_dim=settings.embed_dim,
            )
            run_pipeline(
                connector=connector, dsn=settings.rdb_dsn,
                system="document", dataset="upload",
                ontology_type=ontology_type, match_keys=match_keys,
                graph_url=settings.graph_url, broker=broker,
                on_progress=on_prog,
                fk_links=fk_links, workspace_id=workspace_id,
                relate=True,
            )
        jobs.finish(job_id, run_id=None, status="complete")
    except Exception as exc:  # noqa: BLE001
        logger.warning("file ingest failed job=%s: %s", job_id, exc)
        if jobs is not None:
            jobs.finish(job_id, run_id=None, status="failed", error=str(exc))
    finally:
        if jobs is not None:
            jobs.close()
        for p in tmp_paths:
            p.unlink(missing_ok=True)


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
                raise HTTPException(400, f"{f.filename}: exceeds 50 MB limit")
            total += len(data)
            if total > _MAX_TOTAL:
                raise HTTPException(400, f"Total upload exceeds 500 MB limit")
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
        try:
            links = json.loads(fk_links) if fk_links else []
        except json.JSONDecodeError as exc:
            raise HTTPException(400, f"fk_links is not valid JSON: {exc}") from exc
        for i, lnk in enumerate(links):
            if not isinstance(lnk, dict) or not _FK_REQUIRED_KEYS.issubset(lnk):
                raise HTTPException(400,
                    f"fk_links[{i}] missing required keys: {sorted(_FK_REQUIRED_KEYS)}")
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
                "max_file_mb": 50, "max_total_mb": 500}

    return router
