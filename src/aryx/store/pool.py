"""Shared psycopg3 connection pool — one per DSN, process-scoped (G12)."""
from __future__ import annotations

import logging
import threading

from psycopg_pool import ConnectionPool

logger = logging.getLogger(__name__)

_pools: dict[str, ConnectionPool] = {}
_pool_lock = threading.Lock()


def get_pool(dsn: str, min_size: int = 2, max_size: int = 10) -> ConnectionPool:
    """Return a cached ConnectionPool for the given DSN.

    Creates a new pool on first call for a given DSN; subsequent calls for the
    same DSN return the cached instance. Double-checked locking guards against
    concurrent creation — ConnectionPool() releases the GIL during connect.
    """
    if dsn not in _pools:
        with _pool_lock:
            if dsn not in _pools:
                logger.info("pool: creating min=%d max=%d", min_size, max_size)
                _pools[dsn] = ConnectionPool(
                    conninfo=dsn, min_size=min_size, max_size=max_size, open=True,
                )
    return _pools[dsn]


def close_all() -> None:
    """Close every cached pool and clear the registry (call at shutdown)."""
    with _pool_lock:
        pools = list(_pools.values())
        _pools.clear()
    for pool in pools:
        try:
            pool.close()
        except Exception:  # noqa: BLE001
            pass
    logger.info("pool: all pools closed")
