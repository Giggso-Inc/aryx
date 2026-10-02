"""Per-job count of hidden-failure events (I8-I15), read by ingest.job.completed.

A plain dict keyed by the bound run id (job id). A job that fired any hidden
failure finishes with result="partial" instead of "ok".
"""
from __future__ import annotations

import threading

from aryx.raven_log import current_run_id

_counts: dict[str, int] = {}
_lock = threading.Lock()


def note_hidden(job_id: str | None = None) -> None:
    """Count one hidden failure for the job (defaults to the bound run id)."""
    jid = job_id or current_run_id()
    if not jid:
        return
    with _lock:
        _counts[jid] = _counts.get(jid, 0) + 1


def pop_hidden(job_id: str | None = None) -> int:
    """Return and clear the hidden-failure count for the job."""
    jid = job_id or current_run_id()
    with _lock:
        return _counts.pop(jid, 0)
