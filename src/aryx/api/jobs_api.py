"""Jobs API: live ingestion progress + retention controls (observability)."""
from __future__ import annotations

from typing import Any

from aryx.raven_log import raven_log, would_log

from fastapi import APIRouter, Depends, HTTPException

from aryx.api.security import require_api_key
from aryx.api.workspace_scope import resolve_workspace_id_warn
from aryx.config import get_settings
from aryx.store.job_store import JobStore


def _store() -> JobStore:
    return JobStore(get_settings().effective_dsn())


def _job_in_workspace(jobs: JobStore, job_id: str, workspace_id: int) -> dict[str, Any]:
    """Fetch a job and verify it belongs to `workspace_id`.

    CPQ_Hardcode_Audit_dev_oci_2026-09-25.md T11 New theme A item 3:
    get/events/cancel/resume never filtered by workspace, so any caller who
    could reach these routes could view, cancel, or resume another
    workspace's job (cross-tenant IDOR). A job in a different workspace is
    reported as 404, not 403 -- confirming a job_id exists in someone else's
    workspace is itself a cross-tenant information leak.
    """
    job = jobs.get(job_id)
    if job is None or job.get("workspace_id") != workspace_id:
        raven_log("DEBUG", "P4", "ingest.jobs.scope job hidden from caller",
                  context={"job_id": job_id, "actor_workspace_id": workspace_id, "found": job is not None,
                           "decision": "deny", "reason_code": "NOT_FOUND_OR_OTHER_WORKSPACE"})
        raise HTTPException(status_code=404, detail="job not found")
    if would_log("DEBUG"):
        raven_log("DEBUG", "P4", "ingest.jobs.scope job visible to caller",
                  context={"job_id": job_id, "actor_workspace_id": workspace_id, "decision": "allow",
                           "reason_code": "WORKSPACE_MATCH"})
    return job


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
    def get_job(job_id: str, workspace_id: int | None = None) -> dict[str, Any]:
        workspace_id = resolve_workspace_id_warn(workspace_id, "GET /admin/jobs/{job_id}")
        jobs = _store()
        try:
            return _job_in_workspace(jobs, job_id, workspace_id)
        finally:
            jobs.close()

    @router.get("/jobs/{job_id}/events")
    def get_job_events(job_id: str, workspace_id: int | None = None) -> list[dict[str, Any]]:
        """Live progress events for a job, newest first (≤80 rows)."""
        workspace_id = resolve_workspace_id_warn(
            workspace_id, "GET /admin/jobs/{job_id}/events",
        )
        jobs = _store()
        try:
            _job_in_workspace(jobs, job_id, workspace_id)
            return jobs.events(job_id)
        finally:
            jobs.close()

    @router.post("/jobs/{job_id}/cancel")
    def cancel_job(job_id: str, workspace_id: int | None = None) -> dict[str, Any]:
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
        workspace_id = resolve_workspace_id_warn(
            workspace_id, "POST /admin/jobs/{job_id}/cancel",
        )
        jobs = _store()
        try:
            prior = _job_in_workspace(jobs, job_id, workspace_id)
            jobs.finish(job_id, run_id=None, status="cancelled",
                        error="Cancelled by user")
            raven_log("INFO", "P3", "ingest.job.cancelled user cancelled job",
                      trace_id=job_id,
                      context={"object_id": job_id, "previous_state": prior.get("status"),
                               "requested_state": "cancelled", "final_state": "cancelled", "trigger": "user",
                               "result": "ok", "reason_code": "USER_CANCEL", "workspace_id": workspace_id})
        finally:
            jobs.close()
        return {"status": "cancelled", "job_id": job_id}

    @router.post("/jobs/{job_id}/resume")
    def resume_job(job_id: str, workspace_id: int | None = None) -> dict[str, Any]:
        """Stage-checkpoint status for a job's run (G5).

        Returns the durable per-stage rows so callers can re-submit the
        ingest with ``resume_run_id`` set; done stages will be skipped.
        """
        from aryx.store.checkpoint_store import StageTracker
        workspace_id = resolve_workspace_id_warn(
            workspace_id, "POST /admin/jobs/{job_id}/resume",
        )
        jobs = _store()
        try:
            job = _job_in_workspace(jobs, job_id, workspace_id)
        finally:
            jobs.close()
        if not job.get("run_id"):
            raven_log("DEBUG", "P4", "ingest.jobs.resume no run yet",
                      context={"job_id": job_id, "decision": "refuse", "reason_code": "NO_RUN_ID"})
            raise HTTPException(status_code=404,
                                detail="job not found or has no run yet")
        tracker = StageTracker(get_settings().effective_dsn())
        stages = tracker.rows(int(job["run_id"]))
        return {"job_id": job_id, "run_id": job["run_id"],
                "resumable": any(s["status"] != "done" for s in stages),
                "stages": stages}

    @router.post("/jobs/archive")
    def archive_jobs(days: int = 30, _: str = Depends(require_api_key)) -> dict[str, int]:
        """Purge finished jobs older than `days`, across all workspaces.

        CPQ_Hardcode_Audit_dev_oci_2026-09-25.md T11 New theme A item 3: this
        endpoint carried no auth dependency at all -- any caller could wipe
        every tenant's ingestion history/audit trail. Hard fail-closed via
        require_api_key regardless of ARYX_API_AUTH mode (same pattern as
        admin_api.py::rebuild_graph). Deliberately still global-by-age, not
        per-workspace: this is an age-based retention sweep (see
        archive_old_jobs.sql), the same shape as every other admin
        housekeeping endpoint in this file family -- narrowing it to one
        workspace is a different feature, not this bug's fix.
        """
        jobs = _store()
        try:
            return {"purged": jobs.archive_old(days)}
        finally:
            jobs.close()

    return router
