"""Per-run counters the resolve stages feed and ``resolve_run`` reads for its
single ``ingest.resolve.summary`` record (adjudication_failed, review_dropped,
blocks_skipped_oversized, edge_cap_hit). Logging-only; never affects results.
"""
from __future__ import annotations

import threading
from typing import Any

_lock = threading.Lock()
_stats: dict[Any, dict[str, int]] = {}


def bump(run_id: Any, key: str, n: int = 1) -> None:
    """Add ``n`` to counter ``key`` for ``run_id`` (thread-safe)."""
    with _lock:
        d = _stats.setdefault(run_id, {})
        d[key] = d.get(key, 0) + n


def pop(run_id: Any) -> dict[str, int]:
    """Return and clear the counters for ``run_id`` (empty dict when none)."""
    with _lock:
        return _stats.pop(run_id, {})
