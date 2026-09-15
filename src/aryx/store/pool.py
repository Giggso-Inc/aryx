"""Shared psycopg3 connection pool — one per DSN, process-scoped (G12)."""
from __future__ import annotations

import logging
import os
import threading

from psycopg_pool import ConnectionPool

logger = logging.getLogger(__name__)

_pools: dict[str, ConnectionPool] = {}
_pool_lock = threading.Lock()

# Defaults, overridable via ARYX_DB_POOL_MIN_SIZE/ARYX_DB_POOL_MAX_SIZE --
# 10 was fine for one connection per request, but oracle_graph_reader_
# traverse.py's subgraph() fan-out (_MAX_RTYPE_WORKERS=8) can alone check
# out up to 8 connections for a single /graph request, leaving too little
# headroom for concurrent CPQ turn processing + the web UI's own
# /admin/jobs and /admin/ingest-questions/stats polling in the same
# worker process -- confirmed live: DPY-4005 pool-timeout errors on
# aryx-api-1 with all three kinds of traffic running concurrently, on an
# otherwise-healthy, freshly-restarted container (not a connection leak).
_DEFAULT_POOL_MIN_SIZE = 2
_DEFAULT_POOL_MAX_SIZE = 25


def get_pool(
    dsn: str, min_size: int | None = None, max_size: int | None = None,
) -> ConnectionPool:
    """Return a cached connection pool for the given DSN.

    When ARYX_DB_BACKEND=oci the pool is an OraclePool (oracledb-backed) whose
    interface matches psycopg_pool.ConnectionPool so all store classes stay
    unchanged.  The local default uses psycopg_pool as before.

    Creates a new pool on first call for a given DSN; subsequent calls for the
    same DSN return the cached instance. Double-checked locking guards against
    concurrent creation.

    min_size/max_size default to ARYX_DB_POOL_MIN_SIZE/ARYX_DB_POOL_MAX_SIZE
    (env, falling back to 2/25) when not passed explicitly -- every current
    caller relies on these defaults, so this env var is the only way to tune
    pool sizing without a code change.
    """
    if min_size is None:
        min_size = int(os.environ.get("ARYX_DB_POOL_MIN_SIZE", str(_DEFAULT_POOL_MIN_SIZE)))
    if max_size is None:
        max_size = int(os.environ.get("ARYX_DB_POOL_MAX_SIZE", str(_DEFAULT_POOL_MAX_SIZE)))
    from aryx.config import get_settings
    if get_settings().effective_db_backend() == "oci":
        from aryx.store.oracle_pool import get_oracle_pool  # lazy OCI import
        return get_oracle_pool(dsn, min_size=min_size, max_size=max_size)  # type: ignore[return-value]
    if dsn not in _pools:
        with _pool_lock:
            if dsn not in _pools:
                logger.info("pool: creating min=%d max=%d", min_size, max_size)
                _pools[dsn] = ConnectionPool(
                    conninfo=dsn, min_size=min_size, max_size=max_size, open=True,
                    check=ConnectionPool.check_connection,
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
