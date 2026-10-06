"""Async-compatible wrapper around a synchronous SQLAlchemy Session, so
`app.core.database`'s Oracle branch can use a sync engine (required for
python-oracledb thick mode -- see docs/oci-oracle/
ORACLE_THICK_MODE_MIGRATION_PLAN_2026-10-06.md "shay-api" section: the
async engine hardcodes thin mode in python-oracledb, with no override) while
every one of the ~405 call sites across this codebase that call
`AsyncSessionLocal()` / use `Depends(get_db)` keeps working completely
unchanged.

Why this is safe (confirmed by an Explore pass over this whole codebase
before writing this file, not assumed):
- The only methods actually called anywhere are execute/commit/rollback/
  flush/refresh/close plus add/add_all/delete (never awaited, matching real
  AsyncSession -- those don't do I/O). Nothing exotic (no .get(), .merge(),
  .stream(), .begin() as an async context manager, no .in_transaction()).
- No code holds one session across two concurrent awaits (no
  asyncio.gather/TaskGroup/wait touching a db session anywhere) -- a plain
  sync Session is not safe for *concurrent* multi-thread use, but this
  codebase only ever uses a given session *sequentially*, which is fine
  even when each call happens to run on a different thread-pool thread.

Each I/O-bearing call runs on a dedicated ThreadPoolExecutor (see
_get_executor() below), not the event loop's shared default executor --
the standard pattern for driving a sync-only driver from async code, sized
so DB calls aren't throttled by whatever else in the process happens to
also use asyncio.to_thread()/run_in_executor(None, ...).
"""
from __future__ import annotations

import asyncio
import functools
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from sqlalchemy.orm import Session, sessionmaker

_executor: ThreadPoolExecutor | None = None
_executor_lock = threading.Lock()


def _get_executor() -> ThreadPoolExecutor:
    """Lazily built, process-wide executor dedicated to Oracle session I/O.

    The event loop's *default* executor caps at min(32, cpu_count+4) threads
    (6 on a 2-vCPU container) and is shared with every other asyncio.to_thread()/
    run_in_executor(None, ...) caller in the process -- far below
    DATABASE_POOL_SIZE + DATABASE_MAX_OVERFLOW (30 by default), so a few slow
    queries could starve unrelated to_thread() work, and vice versa. Sizing
    this executor to the pool means at most "pool size" DB calls are ever
    in flight at once anyway, so one thread per potential connection is
    sufficient and doesn't over-subscribe the process.
    """
    global _executor
    if _executor is None:
        with _executor_lock:
            if _executor is None:
                from app.core.config import settings  # noqa: PLC0415 -- avoid import cycle at module load time

                max_workers = settings.DATABASE_POOL_SIZE + settings.DATABASE_MAX_OVERFLOW
                _executor = ThreadPoolExecutor(
                    max_workers=max_workers, thread_name_prefix="oracle-sync-session"
                )
    return _executor


async def _run_sync(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_get_executor(), functools.partial(func, *args, **kwargs))


class AsyncSessionShim:
    """Wraps a sync `Session`, exposing the subset of `AsyncSession`'s
    interface this codebase actually uses."""

    def __init__(self, sync_session: Session) -> None:
        self._sync = sync_session

    async def execute(self, *args: Any, **kwargs: Any) -> Any:
        return await _run_sync(self._sync.execute, *args, **kwargs)

    async def commit(self) -> None:
        await _run_sync(self._sync.commit)

    async def rollback(self) -> None:
        await _run_sync(self._sync.rollback)

    async def flush(self, *args: Any, **kwargs: Any) -> None:
        await _run_sync(self._sync.flush, *args, **kwargs)

    async def refresh(self, *args: Any, **kwargs: Any) -> None:
        await _run_sync(self._sync.refresh, *args, **kwargs)

    async def close(self) -> None:
        # Session.close() already rolls back any uncommitted transaction on
        # its own -- matches AsyncSession's default __aexit__ behavior,
        # no extra rollback call needed here.
        await _run_sync(self._sync.close)

    def add(self, instance: Any) -> None:
        """Not I/O -- marks the object in the identity map only, matching
        real AsyncSession (never awaited at any call site in this codebase)."""
        self._sync.add(instance)

    def add_all(self, instances: Any) -> None:
        self._sync.add_all(instances)

    def delete(self, instance: Any) -> None:
        self._sync.delete(instance)

    async def __aenter__(self) -> "AsyncSessionShim":
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        await self.close()


def make_async_session_local(sync_sessionmaker: sessionmaker) -> Callable[[], AsyncSessionShim]:
    """Returns a zero-arg factory matching `async_sessionmaker`'s own
    callable shape, so `AsyncSessionLocal = make_async_session_local(...)`
    drops in for the existing `AsyncSessionLocal = async_sessionmaker(...)`
    with no change to any `AsyncSessionLocal()` call site."""

    def _factory() -> AsyncSessionShim:
        return AsyncSessionShim(sync_sessionmaker())

    return _factory
