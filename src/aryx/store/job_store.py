"""Durable ingestion-job tracking: live stage progress + 30-day retention.

SQL lives in aryx/queries/*.sql (DB-Guard discipline). Each ingest creates a
job; the pipeline reports stage/% which is persisted as both current state and
an append-only event log (feeds the observability dashboard).
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from aryx.queries import load
from aryx.store.pool import get_pool

logger = logging.getLogger(__name__)

_COLUMNS = ["job_id", "source_system", "source_dataset", "status", "stage",
            "pct", "detail", "run_id", "error", "started_at", "updated_at",
            "finished_at", "workspace_id"]


def _row(values: tuple) -> dict[str, Any]:
    return {col: val for col, val in zip(_COLUMNS, values)}


class JobStore:
    """Persists ingestion jobs and their per-stage progress (Postgres + Oracle ADB)."""

    def __init__(self, dsn: str) -> None:
        """Acquire the shared connection pool for this DSN."""
        self._pool = get_pool(dsn)

    def create(self, job_id: str, system: str, dataset: str, workspace_id: int = 1) -> None:
        """Open a queued job row in a workspace."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(load("lock_workspace_for_mutation"), (workspace_id,))
                if cur.fetchone() is None:
                    raise ValueError(f"workspace {workspace_id} not found")
                cur.execute(load("insert_job"), (workspace_id, job_id, system, dataset))

    def update_stage(self, job_id: str, stage: str, pct: int, detail: str) -> None:
        """Record the current stage and append it to the event log."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(load("update_job_stage"), (stage, pct, detail, job_id))
                cur.execute(load("insert_job_event"), (job_id, stage, pct, detail))

    def finish(self, job_id: str, run_id: int | None, status: str,
               error: str | None = None) -> None:
        """Mark a job complete or failed."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(load("finish_job"), (status, run_id, error, job_id))

    def get(self, job_id: str) -> dict[str, Any] | None:
        """Return one job's current state, or None."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(load("select_job"), (job_id,))
                row = cur.fetchone()
        return _row(row) if row else None

    def list_recent(self, workspace_id: int = 1) -> list[dict[str, Any]]:
        """Return the most recent jobs in a workspace (newest first)."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(load("select_recent_jobs"), (workspace_id,))
                return [_row(r) for r in cur.fetchall()]

    def events(self, job_id: str) -> list[dict[str, Any]]:
        """Return the live event log for one job, newest first."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(load("select_job_events"), (job_id,))
                return [{"stage": r[0], "pct": r[1], "detail": r[2],
                         "ts": r[3]} for r in cur.fetchall()]

    def archive_old(self, days: int = 30) -> int:
        """Archive then purge finished jobs (and old events) older than `days`.

        Returns the number of live job rows deleted.
        """
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(load("archive_old_jobs"), (days,))
                cur.execute(load("delete_old_jobs"), (days,))
                deleted = cur.rowcount
                cur.execute(load("delete_old_job_events"), (days,))
        logger.info("archived/purged jobs older than %d days: %d", days, deleted)
        return deleted

    def sweep_stale(self, timeout_minutes: int) -> int:
        """Mark jobs that haven't updated within timeout_minutes as failed."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(load("sweep_stale_jobs"), (timeout_minutes,))
                count = cur.rowcount
        if count:
            logger.warning("swept %d stale jobs (timeout=%d min)", count, timeout_minutes)
        return count

    def close(self) -> None:
        """No-op: connections are managed by the shared pool (G12)."""


def _make_should_stop(jobs: JobStore, job_id: str, min_interval_s: float = 1.0) -> Callable[[], bool]:
    """Cheap, throttled cancellation check for a running job's worker thread.

    POST /admin/jobs/{job_id}/cancel only ever updated the job-store row
    (see jobs_api.py) -- nothing in the pipeline ever read it back, so a
    "cancelled" job kept running to completion regardless, consuming a
    worker-pool slot the whole time (confirmed live: 20+ minutes of entity
    creation after cancellation). This closure is polled from inside the
    pipeline's hottest loops (dimension_link.py, enrich_relate_isolated.py)
    and at each stage boundary (orchestrate.py) -- real DB reads are
    throttled to at most once per `min_interval_s` regardless of how often
    the caller checks, so callers can poll every iteration without hammering
    Postgres.

    Lives here (not in api.file_ingest.file_ingest_run, where it originated)
    so both file_ingest_run.py (api layer) and doc_discovery.py (pipeline
    layer, the Documents-tab confirm path) can share one implementation
    without pipeline code importing from the api layer -- PR #416 review
    flagged that the Documents-tab confirm path (doc_discovery.ingest_
    confirmed -> run_pipeline) built no should_stop at all and so never
    reached the cancellation support added to _relate_isolated/dimension_link,
    unlike the /admin/ingest/file path.

    Thread-safe: _relate_isolated's ThreadPoolExecutor (relate_workers
    concurrent threads) calls the returned closure from more than one thread
    at a time -- dimension_link and orchestrate.py's stage boundaries only
    ever call it from a single thread. Without the lock below, concurrent
    callers could all pass the `now - last_check < min_interval_s` check
    before any of them updated last_check, each issuing its own
    jobs.get(job_id) -- up to relate_workers DB reads in the same instant
    instead of the promised one. The lock only guards the cheap last_check
    decision, never the DB call itself, so a thread blocked on jobs.get()
    can't stall another thread's cheap "no, not yet" return.
    """
    state = {"last_check": 0.0, "cancelled": False}
    lock = threading.Lock()

    def should_stop() -> bool:
        if state["cancelled"]:
            return True
        now = time.monotonic()
        with lock:
            if state["cancelled"]:
                return True
            if now - state["last_check"] < min_interval_s:
                return False
            state["last_check"] = now
        row = jobs.get(job_id)
        if row is not None and row.get("status") == "cancelled":
            with lock:
                state["cancelled"] = True
        return state["cancelled"]

    return should_stop
