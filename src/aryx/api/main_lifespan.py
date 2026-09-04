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


@asynccontextmanager
async def _lifespan(app: "FastAPI") -> AsyncIterator[None]:
    from aryx.config import get_settings
    from aryx.store.migrate import apply_migrations
    from aryx.api.file_ingest_api import shutdown_executor
    apply_migrations(get_settings().effective_dsn())
    _task = asyncio.ensure_future(_stale_job_sweep())
    try:
        yield
    finally:
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
        shutdown_executor()
        from aryx.store.pool import close_all
        close_all()
