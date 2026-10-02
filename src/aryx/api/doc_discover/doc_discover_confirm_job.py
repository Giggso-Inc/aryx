"""Background job: ingest confirmed discovery types/files.

Split out of `api/doc_discover_api.py` (Raven Style Compliance Plan,
Phase 2b, 2026-09-03). Zero test patches against this module — confirmed
via grep.
"""
from __future__ import annotations

import logging
import time

from aryx import discoveries
from aryx.api.admin_api import _local_broker
from aryx.config import get_settings
from aryx.raven_log import bind_run_id, raven_log
from aryx.worker.job_partial import pop_hidden
from aryx.pipeline.doc_discovery.doc_discovery import ingest_confirmed
from aryx.store.discovery_store import DiscoveryStore
from aryx.store.job_store import JobStore

logger = logging.getLogger(__name__)


def _reset_discovery_status(discovery_id: str) -> None:
    """Reset a discovery back to partial after a confirm job fails."""
    store = DiscoveryStore(get_settings().effective_dsn())
    try:
        store.set_status(discovery_id, "partial")
    except Exception as exc:  # noqa: BLE001
        raven_log("WARN", "P3", "ingest.docconfirm.status_reset_failed discovery status not reset",
                  error_code="ARYX_ING_STATUS_RESET_FAILED",
                  context={"discovery_id": discovery_id, "error_class": type(exc).__name__,
                           "requested_state": "partial", "result": "error"})
    finally:
        store.close()


def _confirm_job(did: str, types: list[str], files: list[str], job_id: str,
                 workspace_id: int = 1, restart: bool = False) -> None:
    bind_run_id(job_id)
    t0 = time.monotonic()
    settings = get_settings()
    jobs = JobStore(settings.effective_dsn())
    try:
        data = discoveries.get(did, workspace_id)
        if not data:
            pop_hidden(job_id)
            raven_log("ERROR", "P2", "ingest.job.failed discovery not found",
                      error_code="ARYX_ING_JOB_FAILED",
                      context={"task_id": job_id, "job_id": job_id, "discovery_id": did, "final_status": "failed",
                               "stage": "lookup", "duration_ms": int((time.monotonic() - t0) * 1000),
                               "result": "error", "reason_code": "DISCOVERY_NOT_FOUND",
                               "error_class": "DiscoveryNotFound"})
            logger.warning("confirm job=%s discovery not found did=%s workspace=%d",
                           job_id, did, workspace_id)
            jobs.finish(job_id, run_id=None, status="failed",
                        error=f"discovery {did} not found or workspace mismatch")
            return
        confirm_state: dict = {} if restart else data.get("_confirm_state", {})
        raven_log("DEBUG", "P4", "ingest.docconfirm.state resume or restart chosen",
                  context={"job_id": job_id, "discovery_id": did, "selected_option": "restart" if restart else "resume",
                           "available_options": ["restart", "resume"], "reason_code": "RESTART_FLAG",
                           "saved_state_keys": len(confirm_state)})
        logger.info("doc confirm start did=%s job=%s types=%s files=%s", did, job_id, types, files)
        ingest_confirmed(data, types, files, _local_broker(), jobs, job_id,
                         workspace_id, confirm_state=confirm_state, discovery_id=did)
        jobs.finish(job_id, run_id=None, status="complete")
        discoveries.mark_confirmed(did, job_id)
        hidden = pop_hidden(job_id)
        raven_log("INFO", "P4", "ingest.job.completed document confirm finished",
                  context={"task_id": job_id, "job_id": job_id, "discovery_id": did, "final_status": "complete",
                           "stage": "finish", "duration_ms": int((time.monotonic() - t0) * 1000),
                           "result": "partial" if hidden else "ok",
                           "reason_code": "HIDDEN_FAILURES" if hidden else "OK",
                           "impact_scope": {"types": len(types), "files": len(files), "hidden_failures": hidden}})
    except Exception as exc:  # noqa: BLE001
        logger.warning("doc confirm failed job=%s: %s", job_id, exc, exc_info=True)
        pop_hidden(job_id)
        raven_log("ERROR", "P2", "ingest.job.failed document confirm failed",
                  error_code="ARYX_ING_JOB_FAILED",
                  context={"task_id": job_id, "job_id": job_id, "discovery_id": did, "final_status": "failed",
                           "stage": "confirm", "duration_ms": int((time.monotonic() - t0) * 1000),
                           "result": "error", "reason_code": type(exc).__name__,
                           "error_class": type(exc).__name__, "error": str(exc)[:300]})
        jobs.finish(job_id, run_id=None, status="failed", error=str(exc))
        _reset_discovery_status(did)
    finally:
        jobs.close()
