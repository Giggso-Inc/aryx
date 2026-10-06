"""
Unit tests for app/core/async_session_shim.py — the AsyncSession-compatible
wrapper around a sync SQLAlchemy Session that lets shay-api's Oracle branch
use a sync engine (required for python-oracledb thick mode) while every
`AsyncSessionLocal()` / `Depends(get_db)` call site keeps working unchanged.

Per the PR #439 review, this file closes three gaps: no direct test of the
shim's method surface, no test that the executor is dedicated rather than
shared, and no guard against the codebase growing a call to a session
method the shim doesn't implement (the "source-scan" test below).

asyncio.run() is used instead of pytest-asyncio (not installed), matching
tests/test_database_characterization.py's pattern. No real DB required —
the wrapped "session" is a plain MagicMock throughout.
"""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path
from unittest.mock import MagicMock

from app.core.async_session_shim import (
    AsyncSessionShim,
    _get_executor,
    make_async_session_local,
)

# The full set of sync-Session methods the shim actually implements --
# the source-scan test below asserts this set is a superset of every
# session method the app/ tree calls.
_SHIM_METHODS = {
    "execute", "commit", "rollback", "flush", "refresh", "close",
    "add", "add_all", "delete",
}


# ---------------------------------------------------------------------------
# Method surface -- each I/O method delegates to the sync session and runs
# off the event loop thread.
# ---------------------------------------------------------------------------
class TestAsyncSessionShimMethodSurface:
    def test_execute_delegates_and_returns_result(self):
        sync_session = MagicMock()
        sync_session.execute.return_value = "the-result"
        shim = AsyncSessionShim(sync_session)

        result = asyncio.run(shim.execute("select 1", {"a": 1}))

        assert result == "the-result"
        sync_session.execute.assert_called_once_with("select 1", {"a": 1})

    def test_commit_delegates(self):
        sync_session = MagicMock()
        asyncio.run(AsyncSessionShim(sync_session).commit())
        sync_session.commit.assert_called_once_with()

    def test_rollback_delegates(self):
        sync_session = MagicMock()
        asyncio.run(AsyncSessionShim(sync_session).rollback())
        sync_session.rollback.assert_called_once_with()

    def test_flush_delegates(self):
        sync_session = MagicMock()
        asyncio.run(AsyncSessionShim(sync_session).flush())
        sync_session.flush.assert_called_once_with()

    def test_refresh_delegates_with_args(self):
        sync_session = MagicMock()
        obj = object()
        asyncio.run(AsyncSessionShim(sync_session).refresh(obj))
        sync_session.refresh.assert_called_once_with(obj)

    def test_close_delegates(self):
        sync_session = MagicMock()
        asyncio.run(AsyncSessionShim(sync_session).close())
        sync_session.close.assert_called_once_with()

    def test_add_is_synchronous_not_io(self):
        """add()/add_all()/delete() are never awaited anywhere in this
        codebase (confirmed by an Explore pass before this shim was written)
        -- they must stay plain sync methods, matching real AsyncSession."""
        sync_session = MagicMock()
        instance = object()
        AsyncSessionShim(sync_session).add(instance)
        sync_session.add.assert_called_once_with(instance)

    def test_add_all_is_synchronous(self):
        sync_session = MagicMock()
        instances = [object(), object()]
        AsyncSessionShim(sync_session).add_all(instances)
        sync_session.add_all.assert_called_once_with(instances)

    def test_delete_is_synchronous(self):
        sync_session = MagicMock()
        instance = object()
        AsyncSessionShim(sync_session).delete(instance)
        sync_session.delete.assert_called_once_with(instance)


class TestAsyncSessionShimContextManager:
    def test_aenter_returns_self(self):
        shim = AsyncSessionShim(MagicMock())
        entered = asyncio.run(shim.__aenter__())
        assert entered is shim

    def test_aexit_closes_the_session(self):
        sync_session = MagicMock()
        shim = AsyncSessionShim(sync_session)
        asyncio.run(shim.__aexit__(None, None, None))
        sync_session.close.assert_called_once_with()


class TestMakeAsyncSessionLocal:
    def test_factory_wraps_a_fresh_session_each_call(self):
        made_sessions = [MagicMock(), MagicMock()]
        sync_sessionmaker = MagicMock(side_effect=made_sessions)

        factory = make_async_session_local(sync_sessionmaker)
        first = factory()
        second = factory()

        assert isinstance(first, AsyncSessionShim)
        assert isinstance(second, AsyncSessionShim)
        assert first._sync is made_sessions[0]
        assert second._sync is made_sessions[1]


# ---------------------------------------------------------------------------
# Executor sizing -- PR #439 review finding: asyncio.to_thread()'s default
# executor is shared process-wide and caps at min(32, cpu_count+4), well
# below DATABASE_POOL_SIZE + DATABASE_MAX_OVERFLOW. The fix is a dedicated
# executor sized to the pool; these tests confirm it exists and is sized
# correctly, without asserting on the live default executor (which this
# fix exists specifically to avoid depending on).
# ---------------------------------------------------------------------------
class TestDedicatedExecutor:
    def test_get_executor_returns_a_singleton(self):
        first = _get_executor()
        second = _get_executor()
        assert first is second

    def test_executor_sized_to_pool_plus_overflow(self):
        from app.core.config import settings

        executor = _get_executor()
        expected = settings.DATABASE_POOL_SIZE + settings.DATABASE_MAX_OVERFLOW
        assert executor._max_workers == expected


# ---------------------------------------------------------------------------
# Source scan -- fails if any code under app/ calls a method on something
# named db/session/async_session that this shim doesn't implement. This is
# the cheap guard the review asked for: AsyncSessionShim stands in for
# ~284 Depends(get_db) call sites, and CI never exercises it directly
# (DATABASE_URL defaults to Postgres, which uses real AsyncSession) -- so a
# future `await db.scalars(...)`/`await db.merge(...)` etc. would only
# fail at runtime, in an Oracle deployment, with no test ever catching it
# first.
# ---------------------------------------------------------------------------
_SESSION_CALL_RE = re.compile(r"\b(?:db|session|async_session)\.(\w+)\(")

# Methods on the *Result* object returned by execute() (`.scalars()`,
# `.scalar_one_or_none()`, `.fetchone()`, ...) are out of scope -- they're
# never called on the session/db variable itself, so they don't match
# _SESSION_CALL_RE and don't need to appear here.


def _iter_app_python_files():
    app_dir = Path(__file__).resolve().parent.parent / "app"
    for path in app_dir.rglob("*.py"):
        yield path


class TestSessionMethodSurfaceCoverage:
    def test_every_called_session_method_is_implemented_by_the_shim(self):
        unimplemented: dict[str, set[str]] = {}
        for path in _iter_app_python_files():
            text = path.read_text(encoding="utf-8")
            called = {m.group(1) for m in _SESSION_CALL_RE.finditer(text)}
            missing = called - _SHIM_METHODS
            if missing:
                unimplemented[str(path)] = missing

        assert not unimplemented, (
            "Code under app/ calls session method(s) AsyncSessionShim doesn't "
            f"implement -- these will only fail at runtime on Oracle (thick "
            f"mode): {unimplemented}. Either add the method to AsyncSessionShim "
            f"(app/core/async_session_shim.py) or confirm it's a false positive "
            f"(e.g. a method on an unrelated object that happens to be named "
            f"db/session/async_session) and narrow _SESSION_CALL_RE / the "
            f"variable name instead."
        )

    def test_the_scan_itself_actually_finds_real_call_sites(self):
        """Guards against the scan silently matching nothing (e.g. if app/
        gets restructured) and the coverage test above passing vacuously."""
        found_any = False
        for path in _iter_app_python_files():
            if _SESSION_CALL_RE.search(path.read_text(encoding="utf-8")):
                found_any = True
                break
        assert found_any, "Source scan found zero db./session. call sites under app/ -- regex or path is stale"
