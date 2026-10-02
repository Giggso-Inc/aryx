"""Stage-checkpoint guard for pipeline runs (G5).

Wraps each pipeline stage in a durable status row: 'running' at entry,
'done' on success, 'failed' on exception. On resume, stages already 'done'
are skipped; a leftover 'running' means the process died — redo the stage.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
import time
from typing import Any, Iterator

from aryx.raven_log import raven_log
from aryx.store.checkpoint_store import StageTracker

logger = logging.getLogger(__name__)


class StageRunner:
    """Per-run stage execution guard with skip-on-resume semantics."""

    def __init__(self, dsn: str, run_id: int, resume: bool) -> None:
        """Load prior stage statuses when resuming."""
        self._tracker = StageTracker(dsn)
        self._run_id = run_id
        self._done: set[str] = set()
        if resume:
            statuses = self._tracker.statuses(run_id)
            self._done = {s for s, st in statuses.items() if st == "done"}
            logger.info("resume run=%s skipping stages=%s",
                        run_id, sorted(self._done))
            raven_log("INFO", "P4", "ingest.stage.resume resume: stages already done will be skipped",
                      context={"task_id": run_id, "selected_option": "resume",
                               "available_options": ["resume", "fresh"], "reason_code": "RESUME_RUN_ID_GIVEN",
                               "stages_done": sorted(self._done), "checkpoint_statuses": statuses})
        else:
            raven_log("DEBUG", "P4", "ingest.stage.fresh fresh run, no stages skipped",
                      context={"task_id": run_id, "selected_option": "fresh",
                               "available_options": ["resume", "fresh"], "reason_code": "NO_RESUME"})

    def skip(self, stage: str) -> bool:
        """True when a resumed run already completed this stage."""
        skipped = stage in self._done
        if skipped:
            raven_log("INFO", "P4", "ingest.stage.skipped stage skipped (checkpoint done)",
                      context={"task_id": self._run_id, "stage": stage, "selected_option": "skip",
                               "available_options": ["run", "skip"], "reason_code": "CHECKPOINT_DONE"})
        else:
            raven_log("DEBUG", "P4", "ingest.stage.not_skipped stage will run",
                      context={"task_id": self._run_id, "stage": stage, "selected_option": "run",
                               "available_options": ["run", "skip"], "reason_code": "NOT_CHECKPOINTED_DONE"})
        return skipped

    @contextmanager
    def stage(self, name: str,
              detail: dict[str, Any] | None = None) -> Iterator[None]:
        """Run one stage under checkpoint accounting."""
        self._tracker.start(self._run_id, name)
        _t0 = time.monotonic()
        raven_log("INFO", "P4", "ingest.stage.started stage started",
                  context={"task_id": self._run_id, "stage": name, "checkpoint_status": "running"})
        try:
            yield
        except Exception as exc:
            self._tracker.fail(self._run_id, name, str(exc))
            raven_log("ERROR", "P2", "ingest.stage.failed stage failed",
                      error_code="ARYX_ING_STAGE_FAILED",
                      context={"task_id": self._run_id, "stage": name, "checkpoint_status": "failed",
                               "final_status": "failed", "result": "error", "error_class": type(exc).__name__,
                               "duration_ms": int((time.monotonic() - _t0) * 1000),
                               "reason_code": "STAGE_EXCEPTION", "impact_scope": "run"})
            raise
        self._tracker.finish(self._run_id, name, detail)
        raven_log("INFO", "P4", "ingest.stage.finished stage finished",
                  context={"task_id": self._run_id, "stage": name, "checkpoint_status": "done",
                           "final_status": "done", "result": "ok",
                           "duration_ms": int((time.monotonic() - _t0) * 1000)})
