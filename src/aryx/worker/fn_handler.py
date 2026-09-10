"""OCI Functions handler — per-document ingest pipeline entry point.

Receives a JSON CloudEvent payload from file_ingest_api.py, decodes the
base64 file, routes to the right connector, and runs the full pipeline.
All DB / graph / LLM config is read from environment variables set in OCI
Console — dsn and graph_url are NOT passed in the payload.

As of the Raven Style Compliance Plan's Phase 2b (2026-09-03), per-file
connector routing moved to `fn_handler_dispatch.py`. This file has no
importers/tests at all (confirmed via grep), so the split was purely
mechanical. `handler` — the OCI Functions entry point — stays here.
"""
from __future__ import annotations

import base64
import io
import json
import logging
import os
from pathlib import Path
from typing import Any

from aryx.worker.fn_handler_dispatch import _dispatch

logger = logging.getLogger(__name__)

__all__ = ["handler"]


def handler(ctx: Any, data: io.BytesIO | None = None) -> Any:
    """OCI Functions entry point — invoked per document, runs full aryx pipeline."""
    from fdk import response as fdk_response  # noqa: PLC0415 — lazy: not installed locally

    from aryx.broker import default_broker, oci_broker  # noqa: PLC0415
    from aryx.config import get_settings  # noqa: PLC0415
    from aryx.logging_setup import configure_logging  # noqa: PLC0415
    from aryx.store.job_store import JobStore  # noqa: PLC0415

    configure_logging(os.environ.get("ARYX_LOG_LEVEL", "INFO"))

    payload: dict[str, Any] = json.loads(data.getvalue())
    _required = {"job_id", "filename", "file_b64", "ontology_type"}
    missing = _required - payload.keys()
    if missing:
        raise ValueError(f"fn_handler: missing required payload fields: {sorted(missing)}")
    job_id        = payload["job_id"]
    workspace_id  = int(payload.get("workspace_id", 1))
    filename      = payload["filename"]
    encoded_b64   = payload["file_b64"]
    # Kept in step with file_ingest_api.py's own _MAX_FILE (raised 2026-09 to
    # 250 MB after a real 223 MB MSI catalog export was rejected). Base64
    # inflates size by ~4/3, so a 250 MB raw file needs headroom well past
    # 250 MB here -- 400 MB encoded covers ~300 MB raw with margin. NOTE:
    # this is Aryx's own app-level guard, not a confirmed OCI Functions
    # platform payload ceiling -- if the real OCI Functions invoke limit is
    # lower than this, a large payload will still fail, just with an
    # OCI-side error instead of this one. That platform limit hasn't been
    # verified in this codebase and should be checked before relying on
    # this path for very large files.
    if len(encoded_b64) > 400 * 1024 * 1024:  # ~300 MB decoded ceiling
        raise ValueError(f"fn_handler: file_b64 exceeds size limit ({len(encoded_b64)} bytes encoded)")
    file_bytes    = base64.b64decode(encoded_b64)
    ontology_type = payload["ontology_type"]
    match_keys    = payload.get("match_keys", [])
    fk_links      = payload.get("fk_links", [])

    # All connectivity from env vars set in OCI Console — never from payload
    settings = get_settings()
    broker   = oci_broker() if settings.effective_llm_cheap_backend() == "oci" else default_broker()
    jobs     = JobStore(settings.effective_dsn())

    logger.info("aryx-ingest-fn: received job_id=%s filename=%s workspace_id=%s",
                job_id, filename, workspace_id)

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
        logger.info("aryx-ingest-fn: completed job_id=%s filename=%s", job_id, filename)
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
