"""CSV ingestion issues API: runs that were skipped / failed / had rejected rows, and re-running them.

Backs the "CSV issues" section of the job card in the web UI. Every route is scoped to a
``workspace_id``; a run that belongs to another workspace is reported as 404 (never 403), the same
rule ``jobs_api`` uses, so ids of other workspaces' runs cannot be probed.

Routes (all under ``/admin/csv-bml``):

* ``GET  /runs``                        stored runs of the workspace (optionally one upload ``job_id``)
* ``GET  /runs/{run_id}``               one run
* ``GET  /runs/{run_id}/rejects``       its rejected rows, paged
* ``GET  /runs/{run_id}/rejects.csv``   download of the rejected rows
* ``POST /runs/{run_id}/rerun-rows``    re-insert the rejected rows (after e.g. widening a column)
* ``POST /runs/{run_id}/rerun-file``    re-run a skipped/failed file through the upload job again
Oracle backend only (``501`` otherwise). Every route requires the API key (the rows hold uploaded data)
and an explicit ``workspace_id``.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from aryx.api.security import require_api_key
from aryx.config import get_settings
from aryx.csv_bml_ingestion.config import csv_bml_enabled
from aryx.csv_bml_ingestion.errors import CsvBmlIngestionError, DatabaseUnavailableError
from aryx.csv_bml_ingestion.issue_store import STATE_OPEN, IssueStore
from aryx.csv_bml_ingestion.overflow import OverflowPolicy
from aryx.csv_bml_ingestion.rejects import csv_safe_cell
from aryx.csv_bml_ingestion.rerun import rerun_rejects
from aryx.raven_log import raven_log

logger = logging.getLogger(__name__)
_MAX_CSV_ROWS = 10_000


def _factory():  # noqa: ANN202
    from aryx.csv_bml_ingestion.db import oracle_connection_factory  # noqa: PLC0415

    try:
        return oracle_connection_factory()
    except DatabaseUnavailableError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc


def _run_or_404(store: IssueStore, workspace_id: int, run_id: str) -> dict[str, Any]:
    run = store.get_run(workspace_id, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return run


def _rejects_csv(rows: list[dict[str, Any]]) -> str:
    """CSV text for download: expanded columns when every row has them, else the row as JSON."""
    out = io.StringIO()
    w = csv.writer(out)
    payloads = [r["row"] or {} for r in rows]
    cols = list(payloads[0]["columns"]) if payloads and all("columns" in p for p in payloads) else None
    if cols and all(list(p["columns"]) == cols for p in payloads):
        w.writerow(["line_no", "reason_code", "reason", *(csv_safe_cell(c) for c in cols)])
        for r, p in zip(rows, payloads):
            w.writerow([r["line_no"], csv_safe_cell(r["reason_code"]), csv_safe_cell(r["reason"]),
                        *(csv_safe_cell(v) for v in p["columns"].values())])
    else:
        w.writerow(["line_no", "reason_code", "reason", "row"])
        for r, p in zip(rows, payloads):
            w.writerow([r["line_no"], csv_safe_cell(r["reason_code"]), csv_safe_cell(r["reason"]),
                        csv_safe_cell(json.dumps(p.get("cells", p), default=str))])
    return out.getvalue()


def csv_bml_router() -> APIRouter:
    router = APIRouter(prefix="/admin/csv-bml", dependencies=[Depends(require_api_key)])

    @router.get("/runs")
    def list_runs(workspace_id: int, job_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        ws = workspace_id
        return IssueStore(_factory()).list_runs(ws, job_id, limit)

    @router.get("/runs/{run_id}")
    def get_run(run_id: str, workspace_id: int) -> dict[str, Any]:
        ws = workspace_id
        return _run_or_404(IssueStore(_factory()), ws, run_id)

    @router.get("/runs/{run_id}/rejects")
    def list_rejects(run_id: str, workspace_id: int, state: str | None = None,
                     offset: int = 0, limit: int = 100) -> list[dict[str, Any]]:
        ws = workspace_id
        store = IssueStore(_factory())
        _run_or_404(store, ws, run_id)
        return store.list_rejects(ws, run_id, state, offset, limit)

    @router.get("/runs/{run_id}/rejects.csv")
    def download_rejects(run_id: str, workspace_id: int) -> Response:
        ws = workspace_id
        store = IssueStore(_factory())
        run = _run_or_404(store, ws, run_id)
        rows: list[dict[str, Any]] = []
        while len(rows) < _MAX_CSV_ROWS:                    # the store pages at 500; a run can hold up to the reject cap
            page = store.list_rejects(ws, run_id, None, len(rows), 500)
            rows.extend(page)
            if len(page) < 500:
                break
        body = _rejects_csv(rows)
        name = f"{(run['table_name'] or 'rejects')}_{run_id[:8]}_rejects.csv"
        return Response(content=body, media_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @router.post("/runs/{run_id}/rerun-rows")
    def rerun_rows(run_id: str, workspace_id: int, policy: str = "reject") -> dict[str, Any]:
        ws = workspace_id
        if policy not in ("reject", "truncate"):
            raise HTTPException(status_code=400, detail="policy must be 'reject' or 'truncate'")
        try:
            return rerun_rejects(_factory(), ws, run_id, OverflowPolicy(policy))
        except CsvBmlIngestionError as exc:
            status = 404 if str(exc) == "run not found" else 409
            raise HTTPException(status_code=status, detail=f"[{exc.code}] {exc}") from exc
        except Exception as exc:  # noqa: BLE001 -- e.g. a database error on insert; the transaction was rolled back
            logger.warning("csv re-run of %s failed: %r", run_id, exc)
            raven_log("WARN", "P3", "ingest.csv_bml.rerun_rows_failed re-run rolled back, 409 returned",
                      error_code="ARYX_ING_CSV_BML_RERUN_FAILED",
                      context={"workspace_id": ws, "csv_run_id": run_id, "policy": policy,
                               "final_status": "failed", "result": "rolled_back",
                               "reason_code": type(exc).__name__, "duration_ms": None, "http_status": 409})
            raise HTTPException(status_code=409, detail=f"re-run failed ({type(exc).__name__}); nothing was changed") from exc

    @router.post("/runs/{run_id}/rerun-file")
    def rerun_file(run_id: str, workspace_id: int) -> dict[str, Any]:
        ws = workspace_id
        if not csv_bml_enabled():
            raise HTTPException(status_code=409, detail="ARYX_CSV_BML_ENABLED is off; the file cannot be re-run")
        settings = get_settings()
        if settings.effective_worker_backend() in ("oci_functions", "oci_dataflow"):
            raise HTTPException(status_code=409, detail="file re-run needs the local worker backend")
        store = IssueStore(_factory())
        run = _run_or_404(store, ws, run_id)
        if run["status"] == "loaded":
            raise HTTPException(status_code=409, detail="this run loaded; use rerun-rows for its rejected rows")
        if run["state"] != STATE_OPEN:
            raise HTTPException(status_code=409, detail=f"this run is already {run['state']}")
        stored = store.get_file(ws, run_id)
        if stored is None:
            raise HTTPException(status_code=409, detail="the file was not kept for re-run; upload it again")
        name, data = stored
        if not store.claim_for_file_rerun(ws, run_id):              # a double click / other tab lost the race
            raise HTTPException(status_code=409, detail="this run is already being re-run")
        from aryx.api.file_ingest.file_ingest_api import _get_executor  # noqa: PLC0415
        from aryx.api.file_ingest.file_ingest_run import _run_files  # noqa: PLC0415
        from aryx.store.job_store import JobStore  # noqa: PLC0415

        job_id = uuid.uuid4().hex
        try:
            jobs = JobStore(settings.effective_dsn())
            try:
                jobs.create(job_id, "upload", f"re-run {name}", ws)
            finally:
                jobs.close()
            future = _get_executor().submit(_run_files, [(data, name)], "csv", ["name"], [], job_id, ws, None)
            future.add_done_callback(lambda f: _rerun_done(f, job_id))
            raven_log("INFO", "P4", "ingest.job.queued csv re-run accepted",
                      context={"job_id": job_id, "workspace_id": ws, "road": "csv_bml_rerun",
                               "csv_run_id": run_id, "file_count": 1, "total_bytes": len(data),
                               "final_status": "queued", "result": "accepted", "reason_code": "JOB_QUEUED",
                               "duration_ms": None, "worker_backend": "local"})
        except Exception as exc:  # noqa: BLE001 -- could not queue: give the run back so the issue stays actionable
            try:
                store.set_run_state(ws, run_id, STATE_OPEN)
            except Exception as give_back_exc:  # noqa: BLE001 -- keep the original failure as the answer
                logger.error("csv re-run of %s: could not give the run back after a queueing failure", run_id, exc_info=True)
                raven_log("ERROR", "P2", "ingest.csv_bml.run_not_given_back run left claimed after a queue failure",
                          error_code="ARYX_ING_CSV_BML_RUN_STUCK",
                          context={"object_id": run_id, "workspace_id": ws, "previous_state": "claimed",
                                   "requested_state": STATE_OPEN, "final_state": "claimed",
                                   "trigger": "queue_failure", "result": "error",
                                   "reason_code": type(give_back_exc).__name__})
            logger.warning("csv re-run of %s could not be queued: %r", run_id, exc)
            raven_log("ERROR", "P2", "ingest.dispatch.failed csv re-run could not be queued, 503 returned",
                      error_code="ARYX_ING_DISPATCH_FAILED",
                      context={"job_id": job_id, "workspace_id": ws, "csv_run_id": run_id,
                               "dependency_name": "local_executor", "operation": "submit", "duration_ms": None,
                               "result": "error", "error_class": type(exc).__name__, "attempt": 1})
            raise HTTPException(status_code=503, detail="could not queue the re-run; try again") from exc
        return {"status": "queued", "job_id": job_id, "file": name}

    return router


def _rerun_done(future: Any, job_id: str) -> None:
    """Done-callback for a csv re-run job: report an exception the worker itself did not catch."""
    exc = future.exception()
    if exc is None:
        return
    logger.error("csv re-run job=%s raised unhandled exception: %s", job_id, exc)
    raven_log("ERROR", "P1", "ingest.job.unhandled csv re-run worker raised past its own catch",
              error_code="ARYX_ING_UNHANDLED",
              context={"job_id": job_id, "final_status": "unknown", "result": "error",
                       "reason_code": type(exc).__name__, "duration_ms": None},
              trace_id=job_id)
