"""App lifespan: run DB migrations on startup, sweep stale jobs, clean shutdown.

Split out of `api/main.py` (Raven Style Compliance Plan, Phase 2b,
2026-09-03). Zero test patches against this module — confirmed via grep.
"""
from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI

from aryx.raven_log import raven_log

logger = logging.getLogger(__name__)


async def _stale_job_sweep() -> None:
    while True:
        await asyncio.sleep(60)
        try:
            from aryx.config import get_settings
            from aryx.store.job_store import JobStore
            timeout_min = int(os.environ.get("ARYX_JOB_TIMEOUT_MINUTES", "120"))
            JobStore(get_settings().effective_dsn()).sweep_stale(timeout_min)
        except Exception as exc:  # noqa: BLE001
            logger.warning("stale-job sweep error: %s", exc)
            raven_log("WARN", "P2", "ingest.sweep.failed stale-job sweep errored",
                      error_code="ARYX_ING_SWEEP_FAILED",
                      context={"dependency_name": "job_store", "operation": "sweep_stale", "result": "error",
                               "error_class": type(exc).__name__, "attempt": 1, "reason_code": "SWEEP_ERROR"})
        # §0 (2026-10-04): a separate, much shorter check for "worker lost"
        # rather than "job legitimately slow" -- see JobStore.sweep_stale_
        # heartbeat's docstring for why these can't share one threshold.
        try:
            from aryx.config import get_settings
            from aryx.store.job_store import JobStore
            heartbeat_min = get_settings().job_heartbeat_timeout_minutes
            JobStore(get_settings().effective_dsn()).sweep_stale_heartbeat(heartbeat_min)
        except Exception as exc:  # noqa: BLE001
            logger.warning("heartbeat-sweep error: %s", exc)
            raven_log("WARN", "P2", "ingest.sweep.heartbeat_failed heartbeat sweep errored",
                      error_code="ARYX_ING_SWEEP_FAILED",
                      context={"dependency_name": "job_store", "operation": "sweep_stale_heartbeat",
                               "result": "error", "error_class": type(exc).__name__,
                               "attempt": 1, "reason_code": "SWEEP_ERROR"})


@asynccontextmanager
async def _lifespan(app: "FastAPI") -> AsyncIterator[None]:
    from aryx.config import get_settings
    from aryx.store.migrate import apply_migrations
    from aryx.api.file_ingest.file_ingest_api import shutdown_executor
    apply_migrations(get_settings().effective_dsn())
    _task = asyncio.ensure_future(_stale_job_sweep())
    # StreamableHTTPSessionManager needs its task group entered before any
    # /mcp request can be served -- set on app.state by _mount_mcp (called
    # in create_app() before the app starts, so it's already there by the
    # time this runs). Absent if MCP mount failed (see _mount_mcp's own
    # except clause), which must not take the whole API down with it.
    mcp_session_manager = getattr(app.state, "mcp_session_manager", None)
    mcp_run_cm = mcp_session_manager.run() if mcp_session_manager is not None else None
    if mcp_run_cm is not None:
        await mcp_run_cm.__aenter__()
    try:
        yield
    finally:
        if mcp_run_cm is not None:
            await mcp_run_cm.__aexit__(None, None, None)
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
        shutdown_executor()
        from aryx.store.pool import close_all
        close_all()
