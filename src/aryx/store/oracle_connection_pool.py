"""Connection wrapper, pool, and thread-safe singleton factory for Oracle
ADB 23ai — the psycopg_pool-compatible surface every store class acquires
connections through.

Split out of `store/oracle_pool.py` (Raven Style Compliance Plan, Phase 2a,
2026-09-03).
"""
from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from typing import Any, Iterator

from aryx.store.oracle_cursor import OracleCursorWrapper

logger = logging.getLogger(__name__)

_oracle_pools: dict[str, "OraclePool"] = {}
_oracle_pool_lock = threading.Lock()


class OracleConnectionWrapper:
    """Wraps an oracledb connection to match the psycopg3 connection API."""

    def __init__(self, raw_conn: Any) -> None:
        self._conn = raw_conn

    @property
    def call_timeout(self) -> int:
        """Per-call timeout in milliseconds (0 = unlimited) — proxies oracledb's connection.call_timeout."""
        return self._conn.call_timeout

    @call_timeout.setter
    def call_timeout(self, value: int) -> None:
        self._conn.call_timeout = value

    def cursor(self, name: str | None = None) -> OracleCursorWrapper:
        """Return a cursor wrapper; ``name`` is accepted but ignored (no server-side cursors)."""
        return OracleCursorWrapper(self._conn.cursor())

    def execute(self, sql: str, params: Any = None) -> OracleCursorWrapper:
        """Execute on a transient cursor (used by WorkspaceStore directly)."""
        cur = OracleCursorWrapper(self._conn.cursor())
        cur.execute(sql, params)
        return cur

    def __enter__(self) -> "OracleConnectionWrapper":
        return self

    def __exit__(self, exc_type: Any, *_: Any) -> None:
        if exc_type is None:
            self._conn.commit()
        else:
            self._conn.rollback()


class OraclePool:
    """oracledb connection pool with a psycopg_pool-compatible interface."""

    def __init__(self, dsn: str, min_size: int = 2, max_size: int = 10) -> None:
        import oracledb  # noqa: PLC0415
        from aryx.config import get_settings  # noqa: PLC0415
        settings = get_settings()
        if not settings.db_user or not settings.db_password:
            raise RuntimeError(
                "ARYX_DB_USER and ARYX_DB_PASSWORD must be set when ARYX_DB_BACKEND=oci"
            )
        logger.info("oracle_pool: creating min=%d max=%d dsn=***", min_size, max_size)
        self._pool = oracledb.create_pool(
            user=settings.db_user,
            password=settings.db_password,
            dsn=dsn,
            min=min_size,
            max=max_size,
            increment=1,
            # POOL_GETMODE_TIMEDWAIT prevents the thin pool's IndexError when all
            # connections are busy — instead of crashing, acquire() raises a proper
            # PoolTimeout after wait_timeout milliseconds.
            getmode=oracledb.POOL_GETMODE_TIMEDWAIT,
            wait_timeout=30000,  # 30 s
            # ping_interval=0: ping every connection before returning it from the
            # pool — detects stale connections (DPY-4011 / broken pipe) that Oracle
            # ADB closed server-side after idle timeout, before they reach user code.
            ping_interval=0,
        )

    @contextmanager
    def connection(self, timeout: float | None = None) -> Iterator[OracleConnectionWrapper]:
        """Acquire a connection from the pool as a context manager.

        Commits on clean exit, rolls back on exception — matches the
        psycopg_pool behaviour that store classes rely on.

        Args:
            timeout: Accepted for interface parity with
                psycopg_pool.ConnectionPool.connection() so callers written
                against that interface (e.g. best-effort background writes
                that must not block on a busy pool) don't raise TypeError
                when running against this Oracle pool instead. Not enforced
                per-call: oracledb's thin pool has no per-acquire wait
                override, only the pool-wide `wait_timeout` set at
                create_pool() time (30s here, see __init__). Worst case with
                a busy pool, a caller passing a short `timeout` waits up to
                that 30s instead — still bounded, and every current caller
                of this parameter already treats acquisition failure as
                best-effort (wrapped in try/except), so a slower-than-
                requested wait is an acceptable trade for not crashing
                outright.

        Yields:
            An `OracleConnectionWrapper` bound to a live connection checked
            out from the pool.

        Raises:
            RuntimeError: If the pool is exhausted (all connections busy
                past oracledb's own wait_timeout).
        """
        del timeout  # see docstring: accepted for interface parity, not enforced
        try:
            raw = self._pool.acquire()
        except IndexError as exc:
            # oracledb thin pool bug: raises IndexError instead of a pool
            # timeout when all connections are in use and TIMEDWAIT is not set.
            raise RuntimeError(
                "oracle_pool: connection acquire failed (pool exhausted)"
            ) from exc
        try:
            yield OracleConnectionWrapper(raw)
            raw.commit()
        except Exception as exc:
            raw.rollback()
            if "DPY-4011" in str(exc) or "Broken pipe" in str(exc):
                logger.warning(
                    "oracle_pool: connection dropped mid-query (DPY-4011) — "
                    "ping_interval=0 should prevent this on acquire; "
                    "if recurring, check ADB idle timeout or network MTU settings"
                )
            raise
        finally:
            self._pool.release(raw)

    def close(self) -> None:
        """Close all connections in the pool."""
        try:
            self._pool.close(force=True)
        except Exception:  # noqa: BLE001
            pass


def get_oracle_pool(dsn: str, min_size: int = 2, max_size: int = 10) -> OraclePool:
    """Return a cached OraclePool for the given DSN (thread-safe singleton)."""
    if dsn not in _oracle_pools:
        with _oracle_pool_lock:
            if dsn not in _oracle_pools:
                _oracle_pools[dsn] = OraclePool(dsn, min_size=min_size, max_size=max_size)
    return _oracle_pools[dsn]


def close_all_oracle() -> None:
    """Close every cached Oracle pool and clear the registry."""
    with _oracle_pool_lock:
        pools = list(_oracle_pools.values())
        _oracle_pools.clear()
    for pool in pools:
        pool.close()
    logger.info("oracle_pool: all pools closed")
