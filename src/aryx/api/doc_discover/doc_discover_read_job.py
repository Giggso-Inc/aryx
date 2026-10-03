"""Background job: read uploaded documents into a discovery snapshot.

Split out of `api/doc_discover_api.py` (Raven Style Compliance Plan,
Phase 2b, 2026-09-03). See tests/test_doc_discover_read_job.py (added
2026-09-30 for the CPQ layout-file diversion) for this module's test
patches.
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path
from tempfile import NamedTemporaryFile

from aryx import discoveries
from aryx.api.admin_api import _local_broker
from aryx.config import get_settings
from aryx.raven_log import bind_run_id, raven_log, would_log
from aryx.log_safe import ora_code
from aryx.worker.job_partial import pop_hidden
from aryx.cpq_ingestion.routing import cpq_layout_upload_active
from aryx.pipeline.doc_discovery.doc_discovery import DATA_EXTS, DOC_EXTS, read_files
from aryx.store.job_store import JobStore

logger = logging.getLogger(__name__)

# Statuses that mean "this job will never write to its discovery row
# again" -- shared with doc_discover_api.py's dismiss() route, which relies
# on it to decide when a discovery is safe to delete. Defined here (not
# there) since this module is where the status actually gets checked
# against the surviving read-job thread's own writes.
JOB_TERMINAL_STATUSES = {"complete", "failed", "cancelled"}


def _is_job_terminal(jobs: JobStore, job_id: str) -> bool:
    row = jobs.get(job_id)
    return row is not None and row.get("status") in JOB_TERMINAL_STATUSES


def _save_tmp(data: bytes, suffix: str) -> Path:
    tmp = NamedTemporaryFile(suffix=suffix, delete=False)
    tmp.write(data)
    tmp.close()
    return Path(tmp.name)


def _build_read_progress(jobs: JobStore, did: str, workspace_id: int) -> Callable[[int, int, list], None]:
    """Build the extract_mentions() progress callback for a read job.

    Durability: on very large (1000+ page) documents, per_doc_timeout can
    expire — or the process can crash — before extraction finishes. Before
    this callback existed, the full mention list was only handed back at the
    very end of read_files(), so any interruption mid-run lost every mention
    extracted so far with nothing recoverable. This callback instead
    persists a growing partial discovery snapshot after every flush, and
    reports real chunk-level progress to the job store (instead of a single
    static "Reading 30%" that never moves until the whole read finishes) --
    the same durability gap and stuck-progress-bar symptom that made a long
    read look identical to a hang.

    Thread safety: with ARYX_DOC_WORKERS > 1, multiple documents' extraction
    threads can call this concurrently — guarded by a lock.

    Cancellation: POST /admin/jobs/{job_id}/cancel only ever flips this job's
    own row to 'cancelled' -- nothing in read_files()/extract_mentions()
    checks should_stop, so the worker thread keeps running and this callback
    keeps firing after a cancel. Each call now checks the job row first and
    skips its write entirely once terminal: without this, dismiss()'s own
    409-while-running guard was pointless -- a cancelled-but-still-running
    read job counts as "terminal" there (safe to dismiss), but the very next
    flush from this still-running thread would silently re-insert the
    'pending' row the user just deleted (put()'s ON CONFLICT never touches
    status, so a fresh INSERT after a delete always lands 'pending' again).
    """
    lock = threading.Lock()
    accumulated: list = []

    def _on_progress(completed: int, total: int, new_records: list) -> None:
        if _is_job_terminal(jobs, did):
            return
        with lock:
            accumulated.extend(new_records)
            pct = 30 + int(min(completed / max(total, 1), 1.0) * 60)
            if would_log("DEBUG"):
                raven_log("DEBUG", "P4", "ingest.docread.progress partial snapshot persisted",
                          trace_id=did,
                          context={"job_id": did, "completed": completed, "total": total, "pct": min(pct, 90),
                                   "new_mentions": len(new_records), "accumulated": len(accumulated)})
            jobs.update_stage(did, "Reading", min(pct, 90),
                              f"Extracted {completed}/{total} chunk(s)…")
            by_type: dict[str, list[str]] = {}
            for m in accumulated:
                by_type.setdefault(m.payload["type"], []).append(m.payload["name"])
            types = [{"type": t, "count": len(v), "examples": list(dict.fromkeys(v))[:5]}
                     for t, v in sorted(by_type.items(), key=lambda kv: -len(kv[1]))]
            discoveries.put(did, {
                "mentions": list(accumulated), "tabular": [],
                "summary": {"types": types, "files": []},
                "workspace_id": workspace_id, "partial": True,
            })

    return _on_progress


def _read_job(items: list[tuple[bytes, str]], context: str, did: str,
              workspace_id: int = 1) -> None:
    bind_run_id(did)
    t0 = time.monotonic()
    settings = get_settings()
    jobs = JobStore(settings.effective_dsn())
    try:
        jobs.update_stage(did, "Reading", 30, f"Reading {len(items)} file(s)…")
        logger.info("doc read start did=%s files=%d context=%r", did, len(items), context)
        # CPQ_LAYOUT_FILE_STORAGE_MIGRATION_PLAN_2026-09-30.md: a layout-
        # export upload (.txt/.json under ARYX_INGEST_PIPELINE=cpq_ingestion
        # + ARYX_CPQ_LAYOUT_SOURCE) is neither a DOC_EXTS document nor a
        # DATA_EXTS tabular source -- pulled out up front so it doesn't fall
        # through both classifications and get silently dropped (files=0),
        # the same bug file_ingest_run.py's _run_files already guards
        # against on the other upload path.
        layout_items = [(d, n) for d, n in items if cpq_layout_upload_active(n)]
        remaining = [(d, n) for d, n in items if not cpq_layout_upload_active(n)]
        doc_paths = [_save_tmp(d, Path(n).suffix) for d, n in remaining
                     if Path(n).suffix.lower() in DOC_EXTS]
        tabular = [(d, n) for d, n in remaining if Path(n).suffix.lower() in DATA_EXTS]
        raven_log("INFO", "P4", "ingest.route.docread split of uploaded files",
                  context={"job_id": did, "selected_option": "read_files", "reason_code": "EXTENSION_SPLIT",
                           "layout_files": len(layout_items), "documents": len(doc_paths),
                           "tabular_files": len(tabular), "other_dropped": len(remaining) - len(doc_paths) - len(tabular)})
        on_progress = _build_read_progress(jobs, did, workspace_id)
        result = read_files(doc_paths, tabular, _local_broker(), context, did=did,
                            on_progress=on_progress, workspace_id=workspace_id,
                            layout_items=layout_items)
        if _is_job_terminal(jobs, did):
            # Cancelled (or otherwise finished) while read_files() was still
            # running -- its own on_progress callback already stopped
            # writing (see _build_read_progress), and this final put() must
            # skip too, or it just re-inserts the 'pending' row dismiss()
            # may have already deleted. Don't overwrite the real terminal
            # status (e.g. 'cancelled') with 'complete' either.
            logger.info("doc read did=%s finished after job was already terminal -- discarding result",
                        did)
            return
        result["workspace_id"] = workspace_id
        discoveries.put(did, result, workspace_id)
        logger.info("doc read complete did=%s mentions=%d tabular_files=%d types=%d",
                    did, len(result.get("mentions", [])), len(result.get("tabular", [])),
                    len(result.get("summary", {}).get("types", [])))
        jobs.finish(did, run_id=None, status="complete")
        hidden = pop_hidden(did)
        raven_log("INFO", "P4", "ingest.job.completed document read finished",
                  context={"task_id": did, "job_id": did, "final_status": "complete", "stage": "finish",
                           "duration_ms": int((time.monotonic() - t0) * 1000),
                           "result": "partial" if hidden else "ok",
                           "reason_code": "HIDDEN_FAILURES" if hidden else "OK",
                           "impact_scope": {"mentions": len(result.get("mentions", [])),
                                            "tabular_files": len(result.get("tabular", [])),
                                            "types": len(result.get("summary", {}).get("types", [])),
                                            "hidden_failures": hidden}})
    except Exception as exc:  # noqa: BLE001
        logger.warning("doc read failed did=%s: %s", did, exc, exc_info=True)
        pop_hidden(did)
        raven_log("ERROR", "P2", "ingest.job.failed document read failed",
                  error_code="ARYX_ING_JOB_FAILED",
                  context={"task_id": did, "job_id": did, "final_status": "failed", "stage": "Reading",
                           "duration_ms": int((time.monotonic() - t0) * 1000), "result": "error",
                           "reason_code": type(exc).__name__, "error_class": type(exc).__name__,
                           "ora_code": ora_code(exc)})
        jobs.finish(did, run_id=None, status="failed", error=str(exc))
    finally:
        jobs.close()
