"""Shared FalkorDB client — one per (host, port), process-scoped.

Mirrors store/pool.py's psycopg_pool pattern (G12) for the graph backend.
Container.graph_reader()/.graph_store() build a fresh GraphReader/FalkorStore
adapter per call because each one binds to a workspace-scoped graph — but
every adapter was also constructing a brand-new FalkorDB(...) client (and
therefore a brand-new redis-py connection pool) to do it. Caching one client
per host/port lets every adapter instance share the same underlying
connection pool instead of opening a new one per request.

select_graph() is cheap — it just wraps the shared client + graph name in a
new Graph object, no I/O — so callers keep calling it per adapter instance
without losing the shared-pool benefit.
"""
from __future__ import annotations

import logging
import threading

from falkordb import FalkorDB

logger = logging.getLogger(__name__)

_clients: dict[tuple[str, int], FalkorDB] = {}
_lock = threading.Lock()


def get_client(host: str, port: int) -> FalkorDB:
    """Return a cached FalkorDB client for the given host/port.

    Double-checked locking guards against concurrent creation of the same
    (host, port) client from two threads on first use.
    """
    key = (host, port)
    if key not in _clients:
        with _lock:
            if key not in _clients:
                logger.info("falkordb client_pool: creating shared client for %s:%d", host, port)
                _clients[key] = FalkorDB(host=host, port=port)
    return _clients[key]


def close_all() -> None:
    """Close every cached client and clear the registry (call at shutdown)."""
    with _lock:
        clients = list(_clients.values())
        _clients.clear()
    for client in clients:
        try:
            client.connection.close()
        except Exception:  # noqa: BLE001
            pass
    logger.info("falkordb client_pool: all clients closed")
