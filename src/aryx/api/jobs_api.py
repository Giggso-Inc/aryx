"""Jobs API: live ingestion progress + retention controls (observability)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from aryx.config import get_settings
from aryx.store.job_store import JobStore


def _store() -> JobStore:
    return JobStore(get_settings().rdb_dsn)


def jobs_router() -> APIRouter:
    router = APIRouter(prefix="/admin")

    @router.get("/jobs")
    def list_jobs(workspace_id: int = 1) -> list[dict[str, Any]]:
        jobs = _store()
        try:
            return jobs.list_recent(workspace_id)
        finally:
            jobs.close()

    @router.get("/jobs/{job_id}")
    def get_job(job_id: str) -> dict[str, Any]:
        jobs = _store()
        try:
            job = jobs.get(job_id)
        finally:
            jobs.close()
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        return job

    @router.get("/jobs/{job_id}/events")
    def get_job_events(job_id: str) -> list[dict[str, Any]]:
        """Live progress events for a job, newest first (≤80 rows)."""
        jobs = _store()
        try:
            return jobs.events(job_id)
        finally:
            jobs.close()

    @router.post("/jobs/{job_id}/cancel")
    def cancel_job(job_id: str) -> dict[str, Any]:
        """Mark a job cancelled so the UI frees up, AND actually stop it.

        The running worker thread polls this row via `should_stop()`
        (see file_ingest_api._make_should_stop) at every pipeline stage
        boundary and inside the dimension-linking loop specifically — the
        stage previously observed running for 20+ minutes after a
        "cancel" that only ever updated this row. A thread genuinely
        blocked inside a single synchronous LLM call still can't be
        force-killed mid-call (that limitation is real and unchanged) —
        but it stops at the next check afterward instead of running the
        rest of the pipeline to completion. Any later progress write from
        a still-stopping thread is ignored because this row is terminal.
        """
        jobs = _store()
        try:
            job = jobs.get(job_id)
            if job is None:
                raise HTTPException(status_code=404, detail="job not found")
            jobs.finish(job_id, run_id=None, status="cancelled",
                        error="Cancelled by user")
        finally:
            jobs.close()
        return {"status": "cancelled", "job_id": job_id}

    @router.post("/jobs/{job_id}/resume")
    def resume_job(job_id: str) -> dict[str, Any]:
        """Stage-checkpoint status for a job's run (G5).

        Returns the durable per-stage rows so callers can re-submit the
        ingest with ``resume_run_id`` set; done stages will be skipped.
        """
        from aryx.store.checkpoint_store import StageTracker
        jobs = _store()
        try:
            job = jobs.get(job_id)
        finally:
            jobs.close()
        if job is None or not job.get("run_id"):
            raise HTTPException(status_code=404,
                                detail="job not found or has no run yet")
        tracker = StageTracker(get_settings().rdb_dsn)
        stages = tracker.rows(int(job["run_id"]))
        return {"job_id": job_id, "run_id": job["run_id"],
                "resumable": any(s["status"] != "done" for s in stages),
                "stages": stages}

    @router.post("/jobs/archive")
    def archive_jobs(days: int = 30) -> dict[str, int]:
        jobs = _store()
        try:
            return {"purged": jobs.archive_old(days)}
        finally:
            jobs.close()

    return router
