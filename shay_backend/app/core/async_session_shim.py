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

Each I/O-bearing call runs via asyncio.to_thread() so it doesn't block the
event loop -- the standard pattern for driving a sync-only driver from
async code.
"""
from __future__ import annotations

import asyncio
from typing import Any, Callable

from sqlalchemy.orm import Session, sessionmaker


class AsyncSessionShim:
    """Wraps a sync `Session`, exposing the subset of `AsyncSession`'s
    interface this codebase actually uses."""

    def __init__(self, sync_session: Session) -> None:
        self._sync = sync_session

    async def execute(self, *args: Any, **kwargs: Any) -> Any:
        return await asyncio.to_thread(self._sync.execute, *args, **kwargs)

    async def commit(self) -> None:
        await asyncio.to_thread(self._sync.commit)

    async def rollback(self) -> None:
        await asyncio.to_thread(self._sync.rollback)

    async def flush(self, *args: Any, **kwargs: Any) -> None:
        await asyncio.to_thread(self._sync.flush, *args, **kwargs)

    async def refresh(self, *args: Any, **kwargs: Any) -> None:
        await asyncio.to_thread(self._sync.refresh, *args, **kwargs)

    async def close(self) -> None:
        # Session.close() already rolls back any uncommitted transaction on
        # its own -- matches AsyncSession's default __aexit__ behavior,
        # no extra rollback call needed here.
        await asyncio.to_thread(self._sync.close)

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
