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
import time
from pathlib import Path
from typing import Any

from aryx.raven_log import bind_run_id, raven_log
from aryx.log_safe import ora_code
from aryx.worker.fn_handler_dispatch import _dispatch
from aryx.worker.job_partial import pop_hidden

logger = logging.getLogger(__name__)

__all__ = ["handler"]

# Kept in step with file_ingest_api.py's own _MAX_FILE. Raised 2026-09-11
# (PR #326) to 500 MB; this constant went stale at the old 250 MB
# generation and started rejecting valid 400-500 MB files on this
# OCI-Functions path that the direct-upload path already accepted --
# confirmed 2026-09-16 during the jsonb-string-limit incident sweep.
# Base64 inflates size by ~4/3, so a 500 MB raw file needs headroom well
# past 500 MB here -- 800 MB encoded covers ~600 MB raw, the same ~20%
# margin the previous 250->300 MB generation used. NOTE: this is Aryx's
# own app-level guard, not a confirmed OCI Functions platform payload
# ceiling -- if the real OCI Functions invoke limit is lower than this, a
# large payload will still fail, just with an OCI-side error instead of
# this one. That platform limit hasn't been verified in this codebase
# and should be checked before relying on this path for very large files.
_MAX_ENCODED_B64_BYTES = 800 * 1024 * 1024  # ~600 MB decoded ceiling


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
    bind_run_id(job_id)
    t0 = time.monotonic()
    workspace_id  = int(payload.get("workspace_id", 1))
    filename      = payload["filename"]
    encoded_b64   = payload["file_b64"]
    if len(encoded_b64) > _MAX_ENCODED_B64_BYTES:
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
    raven_log("INFO", "P4", "ingest.fn.received OCI Function entry",
              context={"job_id": job_id, "workspace_id": workspace_id, "filename": filename,
                       "suffix": Path(filename).suffix.lower(), "encoded_bytes": len(encoded_b64),
                       "decoded_bytes": len(file_bytes), "llm_cheap_backend": settings.effective_llm_cheap_backend(),
                       "selected_option": "oci_broker" if settings.effective_llm_cheap_backend() == "oci" else "default_broker",
                       "available_options": ["oci_broker", "default_broker"], "reason_code": "LLM_CHEAP_BACKEND"})

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
        hidden = pop_hidden(job_id)
        raven_log("INFO", "P4", "ingest.job.completed OCI Function ingest finished",
                  context={"task_id": job_id, "job_id": job_id, "final_status": "complete", "stage": "finish",
                           "duration_ms": int((time.monotonic() - t0) * 1000),
                           "result": "partial" if hidden else "ok",
                           "reason_code": "HIDDEN_FAILURES" if hidden else "OK",
                           "impact_scope": {"files_total": 1, "hidden_failures": hidden}})
        return fdk_response.Response(
            ctx,
            response_data=json.dumps({"status": "ok", "job_id": job_id}),
            headers={"Content-Type": "application/json"},
        )

    except Exception as exc:  # noqa: BLE001
        logger.exception("aryx-ingest-fn failed job=%s", job_id)
        pop_hidden(job_id)
        raven_log("ERROR", "P2", "ingest.job.failed OCI Function ingest failed",
                  error_code="ARYX_ING_JOB_FAILED",
                  context={"task_id": job_id, "job_id": job_id, "final_status": "failed", "stage": "dispatch",
                           "duration_ms": int((time.monotonic() - t0) * 1000), "result": "error",
                           "reason_code": type(exc).__name__, "error_class": type(exc).__name__,
                           "ora_code": ora_code(exc)})
        jobs.finish(job_id, run_id=None, status="failed", error=str(exc))
        return fdk_response.Response(
            ctx,
            response_data=json.dumps({"status": "error", "detail": str(exc)}),
            status_code=500,
            headers={"Content-Type": "application/json"},
        )

    finally:
        jobs.close()
