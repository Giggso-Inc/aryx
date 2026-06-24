"""OCI Functions handler — per-document ingest pipeline entry point.

Receives a JSON CloudEvent payload from file_ingest_api.py, decodes the
base64 file, routes to the right connector, and runs the full pipeline.
All DB / graph / LLM config is read from environment variables set in OCI
Console — dsn and graph_url are NOT passed in the payload.
"""
from __future__ import annotations

import base64
import io
import json
import logging
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DATA_EXTS = {".json", ".csv"}
_DOC_EXTS = {
    ".pdf", ".pptx", ".ppt", ".docx", ".doc", ".rtf",
    ".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp",
}


def _dispatch(
    suffix: str,
    file_bytes: bytes,
    filename: str,
    settings: Any,
    broker: Any,
    on_progress: Any,
    ontology_type: str,
    match_keys: list,
    fk_links: list,
    workspace_id: int,
) -> None:
    """Route one file to the correct connector and run the full ingest pipeline."""
    from aryx.connectors.csv_source import CsvConnector  # noqa: PLC0415
    from aryx.connectors.doc_router import DocumentRouterConnector  # noqa: PLC0415
    from aryx.connectors.json_source import JsonConnector  # noqa: PLC0415
    from aryx.pipeline.orchestrate import run_pipeline  # noqa: PLC0415
    from aryx.store.chunk_store import ChunkStore  # noqa: PLC0415

    tmp_path: Path | None = None
    _run: dict[str, Any] = dict(
        dsn=settings.rdb_dsn,
        ontology_type=ontology_type,
        match_keys=match_keys,
        graph_url=settings.graph_url,
        broker=broker,
        on_progress=on_progress,
        fk_links=fk_links,
        workspace_id=workspace_id,
    )
    try:
        if suffix == ".json":
            tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
            tmp.write(file_bytes)
            tmp.close()
            tmp_path = Path(tmp.name)
            connector = JsonConnector(tmp_path, system="json")
            run_pipeline(connector=connector, system="json",
                         dataset=Path(filename).stem, **_run)

        elif suffix == ".csv":
            connector = CsvConnector(file_bytes, system="csv",
                                     dataset=Path(filename).stem)
            run_pipeline(connector=connector, system="csv",
                         dataset=Path(filename).stem, **_run)

        elif suffix in _DOC_EXTS:
            tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
            tmp.write(file_bytes)
            tmp.close()
            tmp_path = Path(tmp.name)
            chunk_store = ChunkStore(settings.rdb_dsn)
            connector = DocumentRouterConnector(
                paths=[tmp_path],
                system="document",
                broker=broker,
                chunk_store=chunk_store,
                chunk_size=settings.chunk_size,
                chunk_overlap=settings.chunk_overlap,
                expected_embed_dim=settings.embed_dim,
            )
            run_pipeline(connector=connector, system="document",
                         dataset="upload", **_run)

        else:
            raise ValueError(f"Unsupported file type: {suffix!r}")

    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)


def handler(ctx: Any, data: io.BytesIO | None = None) -> Any:
    """OCI Functions entry point — invoked per document, runs full aryx pipeline."""
    from fdk import response as fdk_response  # noqa: PLC0415 — lazy: not installed locally

    from aryx.broker import default_broker, oci_broker  # noqa: PLC0415
    from aryx.config import get_settings  # noqa: PLC0415
    from aryx.store.job_store import JobStore  # noqa: PLC0415

    payload: dict[str, Any] = json.loads(data.getvalue())
    _required = {"job_id", "filename", "file_b64", "ontology_type"}
    missing = _required - payload.keys()
    if missing:
        raise ValueError(f"fn_handler: missing required payload fields: {sorted(missing)}")
    job_id        = payload["job_id"]
    workspace_id  = int(payload.get("workspace_id", 1))
    filename      = payload["filename"]
    encoded_b64   = payload["file_b64"]
    if len(encoded_b64) > 70 * 1024 * 1024:  # ~52 MB decoded ceiling
        raise ValueError(f"fn_handler: file_b64 exceeds size limit ({len(encoded_b64)} bytes encoded)")
    file_bytes    = base64.b64decode(encoded_b64)
    ontology_type = payload["ontology_type"]
    match_keys    = payload.get("match_keys", [])
    fk_links      = payload.get("fk_links", [])

    # All connectivity from env vars set in OCI Console — never from payload
    settings = get_settings()
    broker   = oci_broker() if settings.effective_llm_cheap_backend() == "oci" else default_broker()
    jobs     = JobStore(settings.rdb_dsn)

    try:
        suffix = Path(filename).suffix.lower()
        jobs.update_stage(job_id, "Ingest", 10, f"Starting {filename}")
        _dispatch(
            suffix=suffix,
            file_bytes=file_bytes,
            filename=filename,
            settings=settings,
            broker=broker,
            on_progress=lambda s, p, d: jobs.update_stage(job_id, s, p, d),
            ontology_type=ontology_type,
            match_keys=match_keys,
            fk_links=fk_links,
            workspace_id=workspace_id,
        )
        jobs.finish(job_id, run_id=None, status="complete")
        return fdk_response.Response(
            ctx,
            response_data=json.dumps({"status": "ok", "job_id": job_id}),
            headers={"Content-Type": "application/json"},
        )

    except Exception as exc:  # noqa: BLE001
        logger.exception("aryx-ingest-fn failed job=%s", job_id)
        jobs.finish(job_id, run_id=None, status="failed", error=str(exc))
        return fdk_response.Response(
            ctx,
            response_data=json.dumps({"status": "error", "detail": str(exc)}),
            status_code=500,
            headers={"Content-Type": "application/json"},
        )

    finally:
        jobs.close()
