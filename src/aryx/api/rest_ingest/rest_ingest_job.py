"""Entity-type inference + the background REST-ingest job.

Split out of `api/rest_ingest_api.py` (Raven Style Compliance Plan,
Phase 2b, 2026-09-03). Zero test patches against this module — confirmed
via grep.
"""
from __future__ import annotations

import logging
import re
import time

from aryx.api.admin_api import _local_broker
from aryx.config import get_settings
from aryx.raven_log import bind_run_id, raven_log
from aryx.log_safe import ora_code
from aryx.worker.job_partial import pop_hidden
from aryx.connectors.rest_api import RestApiConnector
from aryx.pipeline.orchestrate import run_pipeline
from aryx.store.job_store import JobStore

logger = logging.getLogger(__name__)


def _type_from_url(url: str) -> str:
    """Derive a PascalCase entity type from the last non-empty URL path segment.

    https://api.example.com/v1/customers  ->  Customer
    https://api.example.com/v1/support-tickets  ->  SupportTicket
    """
    path = url.split("?")[0].rstrip("/")
    segment = path.split("/")[-1] if "/" in path else path
    segment = re.sub(r"[^a-zA-Z0-9 ]", " ", segment).strip()
    words = [w for w in segment.replace("-", " ").replace("_", " ").split() if w]
    if not words:
        return "Entity"
    def _singular(w: str) -> str:
        if w.endswith("ies"):
            return w[:-3] + "y"
        if len(w) > 2 and w.endswith("s") and not w.endswith("ss"):
            return w[:-1]
        return w
    return "".join(_singular(w).title() for w in words)


def _run_rest(url: str, headers: dict, record_path: str, page_param: str,
              next_page_path: str, max_pages: int, ontology_type: str,
              match_keys: list[str], job_id: str, workspace_id: int) -> None:
    bind_run_id(job_id)
    t0 = time.monotonic()
    stage_seen = ["Fetch"]
    settings = get_settings()
    jobs = None
    try:
        jobs = JobStore(settings.effective_dsn())
        jobs.update_stage(job_id, "Fetch", 10, f"Fetching from {url}")
        connector = RestApiConnector(
            url=url, headers=headers, record_path=record_path,
            page_param=page_param, next_page_path=next_page_path,
            max_pages=max_pages,
        )
        run_pipeline(
            connector=connector, dsn=settings.effective_dsn(),
            system="rest", dataset=url,
            ontology_type=ontology_type, match_keys=match_keys,
            graph_url=settings.graph_url, broker=_local_broker(),
            on_progress=lambda s, p, d: (stage_seen.__setitem__(0, s), jobs.update_stage(job_id, s, p, d))[1],
            workspace_id=workspace_id,
            relate=True,
        )
        jobs.finish(job_id, run_id=None, status="complete")
        hidden = pop_hidden(job_id)
        raven_log("INFO", "P4", "ingest.job.completed rest ingest finished",
                  context={"task_id": job_id, "job_id": job_id, "final_status": "complete", "stage": "finish",
                           "duration_ms": int((time.monotonic() - t0) * 1000),
                           "result": "partial" if hidden else "ok",
                           "reason_code": "HIDDEN_FAILURES" if hidden else "OK",
                           "impact_scope": {"max_pages": max_pages, "hidden_failures": hidden}})
    except Exception as exc:  # noqa: BLE001
        logger.warning("rest ingest failed job=%s: %s", job_id, exc)
        pop_hidden(job_id)
        raven_log("ERROR", "P2", "ingest.job.failed rest ingest failed",
                  error_code="ARYX_ING_JOB_FAILED",
                  context={"task_id": job_id, "job_id": job_id, "final_status": "failed", "stage": stage_seen[0],
                           "duration_ms": int((time.monotonic() - t0) * 1000), "result": "error",
                           "reason_code": type(exc).__name__, "error_class": type(exc).__name__,
                           "ora_code": ora_code(exc)})
        if jobs is not None:
            jobs.finish(job_id, run_id=None, status="failed", error=str(exc))
    finally:
        if jobs is not None:
            jobs.close()
