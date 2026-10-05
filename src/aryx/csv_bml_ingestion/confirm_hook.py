"""CSV -> Oracle ingestion from the Documents flow (Ingest -> Documents -> Read & discover -> Confirm).

The upload route ``POST /admin/ingest/file`` already sends CSVs through ``CsvBmlUploadSession`` (see
``upload_hook``). The Documents flow is a different route (``/admin/docs/read`` then ``/admin/docs/confirm``), so
``doc_discovery.ingest_confirmed`` calls ``ingest_csv_plans_with_bml`` here when ``ARYX_CSV_BML_ENABLED`` is on.

It is *additive*: the confirm step keeps landing the CSV the way it always did; this only adds the BML-driven table
(``ws<workspace id>_<file stem>``) for every plain CSV the user approved. Plain means: a ``.csv`` upload that is not
derived from an XML/XLSX parent and is not a CPQ layout file. A CSV that no query in the workspace's XML knowledge
graph reads is skipped with ``CBI_BML_NOT_FOUND`` and stored as an issue (rows/files can be re-run from the Jobs
panel); it never fails the confirm job. Everything here is best effort: nothing in this module may raise.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Sequence

from aryx.csv_bml_ingestion.options import IngestResult
from aryx.csv_bml_ingestion.upload_hook import CsvBmlUploadSession
from aryx.raven_log import raven_log
from aryx.worker.job_partial import note_hidden

logger = logging.getLogger(__name__)

CSV_SUFFIX = ".csv"
LAYOUT_KIND = "cpq_layout"
STATUS_LOADED = "loaded"
CANCELLED_CODE = "ARYX_ING_CANCELLED"     # the code the other ingestion stages use when a job is cancelled


def bml_csv_plans(plans: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """The approved plans that are plain CSV uploads (not derived from XML/XLSX, not a CPQ layout file)."""
    return [p for p in plans
            if Path(str(p.get("filename", ""))).suffix.lower() == CSV_SUFFIX
            and not p.get("source_filename") and p.get("kind") != LAYOUT_KIND]


def ingest_csv_plans_with_bml(
    plans: Sequence[dict[str, Any]],
    *,
    workspace_id: int,
    job_id: str | None,
    on_stage: Callable[[str], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> list[IngestResult]:
    """Run each plain CSV plan through ``CsvBmlUploadSession``; returns one result per file. Never raises.

    ``should_stop`` is the job's cancellation check, asked before each file: once it says stop, the remaining files
    are left alone (a load can involve LLM SQL authoring and be slow, so cancelling must not wait for all of them).
    """
    results: list[IngestResult] = []
    try:
        session = CsvBmlUploadSession(workspace_id, job_id)
    except Exception as exc:  # noqa: BLE001 -- the confirm job must carry on without this extra step
        logger.warning("csv_bml_ingestion: could not start for workspace %s: %r", workspace_id, exc)
        return results
    selected = bml_csv_plans(plans)
    for index, plan in enumerate(selected):
        if _stopped(should_stop):
            _report_cancelled([str(p["filename"]) for p in selected[index:]], job_id, workspace_id)
            break
        name = str(plan["filename"])
        _stage(on_stage, f"Processing {name} (csv_bml_ingestion)")
        try:
            result = session.ingest(plan["data"], name)
        except Exception as exc:  # noqa: BLE001 -- ``ingest`` never raises by contract; belt and braces
            logger.warning("csv_bml_ingestion: %s failed unexpectedly: %r", name, exc)
            result = IngestResult(source=name, status="failed", error_code="CBI_UNEXPECTED",
                                  message=f"unexpected {type(exc).__name__}")
        results.append(result)
        _report(result, job_id, workspace_id)
    return results


def _report_cancelled(skipped: list[str], job_id: str | None, workspace_id: int) -> None:
    """The job was cancelled mid-way: say which CSVs were left alone (a WARN, and one hidden problem on the job)."""
    logger.warning("csv_bml_ingestion: job %s cancelled, %d file(s) not processed: %s", job_id, len(skipped), skipped)
    note_hidden(job_id)
    raven_log("WARN", "P3", "ingest.csv_bml.cancelled remaining CSV files not processed after the job was cancelled",
              error_code=CANCELLED_CODE,
              context={"job_id": job_id, "workspace_id": workspace_id, "files_skipped": skipped,
                       "recovery_selected": "stop_remaining_files", "fallback_target": None,
                       "exit_condition": "cancelled", "result": "cancelled"})


def _stopped(should_stop: Callable[[], bool] | None) -> bool:
    if should_stop is None:
        return False
    try:
        return bool(should_stop())
    except Exception as exc:  # noqa: BLE001 -- a failing cancel check must not stop or break the ingestion
        logger.debug("csv_bml_ingestion: cancel check failed: %r", exc)
        return False


def _stage(on_stage: Callable[[str], None] | None, detail: str) -> None:
    if on_stage is None:
        return
    try:
        on_stage(detail)
    except Exception as exc:  # noqa: BLE001 -- a progress update must never stop an ingestion
        logger.debug("csv_bml_ingestion: stage update failed: %r", exc)


def _report(result: IngestResult, job_id: str | None, workspace_id: int) -> None:
    """One Raven record per file: INFO when it loaded, WARN (and a 'hidden problem' on the job) when not."""
    table = result.physical_table or result.table
    context = {"job_id": job_id, "workspace_id": workspace_id, "filename": result.source, "table": table,
               "status": result.status, "rows_loaded": result.rows_loaded, "rows_rejected": result.rows_rejected}
    if result.status == STATUS_LOADED:
        logger.info("csv_bml_ingestion: %s loaded %d row(s) into %s", result.source, result.rows_loaded, table)
        raven_log("INFO", "P4", "ingest.csv_bml.loaded CSV loaded into its workspace table", context=context)
        return
    logger.warning("csv_bml_ingestion: %s %s [%s] %s", result.source, result.status, result.error_code, result.message)
    note_hidden(job_id)
    raven_log("WARN", "P3", "ingest.csv_bml.not_loaded CSV not loaded into a workspace table, see stored issues",
              error_code=result.error_code or "CBI_UNEXPECTED",
              context={**context, "reason_code": result.error_code, "recovery_selected": "continue_confirm",
                       "fallback_target": None, "exit_condition": result.status, "result": result.status})
