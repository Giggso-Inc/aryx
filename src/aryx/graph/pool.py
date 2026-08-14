"""Shared FalkorDB adapter pool — one per (url, graph), process-scoped.

docs/FALKORDB_QUERY_EXHAUSTION_2026_08_14.md (F1) -- Container.graph_reader()/
.graph_store() used to construct a brand-new GraphReader/FalkorStore (and
therefore a brand-new FalkorDB client) on every single call, with no reuse
across requests. Mirrors the pattern already proven for Postgres in
store/pool.py: one cached instance per key, created once, reused after.

Keyed by "url::graph" rather than just workspace_id so it stays correct even
if graph_url ever varies across environments/tests -- two different
workspaces already get different keys via ws_graph(workspace_id), so no
cross-workspace data ever shares one cached adapter.
"""
from __future__ import annotations

import threading
from typing import Any

_readers: dict[str, Any] = {}
_stores: dict[str, Any] = {}
_lock = threading.Lock()


def get_graph_reader(cls: type, url: str, graph: str) -> Any:
    """Return a cached reader adapter for (url, graph), constructing it once.

    `cls` is passed in (rather than imported here) so the container stays
    the single place that resolves which adapter class is active -- this
    module only caches instances, never decides which class to use.
    """
    key = f"{url}::{graph}"
    if key not in _readers:
        with _lock:
            if key not in _readers:
                _readers[key] = cls(url, graph)
    return _readers[key]


def get_graph_store(cls: type, url: str, graph: str) -> Any:
    """Return a cached store adapter for (url, graph), constructing it once."""
    key = f"{url}::{graph}"
    if key not in _stores:
        with _lock:
            if key not in _stores:
                _stores[key] = cls(url, graph)
    return _stores[key]


def clear_all() -> None:
    """Drop every cached adapter (test isolation; GraphReader/FalkorStore
    define no close() method today, so there is nothing to close -- this
    just lets the next get_graph_reader/get_graph_store call construct
    fresh instances)."""
    with _lock:
        _readers.clear()
        _stores.clear()
