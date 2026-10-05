"""Chunk-backend protocol + the key pass (streaming block-key persistence).

Split out of `resolution/chunked.py` (Raven Style Compliance Plan, Phase
2b, 2026-09-03). Zero patch risk — confirmed via grep (neither calls
`get_settings()`/`_materialize`, the two patched names in this module).
"""
from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Iterator
from typing import Protocol

from aryx.models import ResolutionRecord
from aryx.raven_log import raven_log
from aryx.resolution.blocking import _keys_for

logger = logging.getLogger(__name__)

Progress = Callable[[str, int, str], None]

# How often (in persisted membership rows) the key pass logs progress —
# this pass was previously silent between "raw graph nodes extracted" and
# "resolve path: chunked" finishing, making a multi-hundred-thousand-record
# run look stalled.
_KEY_PASS_LOG_EVERY = 50_000


class ChunkBackend(Protocol):
    """Persistence the chunked resolver needs (Postgres in prod, dict in tests)."""

    def has_keys(self, run_id: int) -> bool: ...
    def add_members(self, run_id: int, rows: list[tuple[str, int]]) -> None: ...
    def todo_blocks(self, run_id: int) -> Iterator[str]: ...
    def block_record_ids(self, run_id: int, key: str) -> list[int]: ...
    def load_records(self, ids: list[int]) -> list[ResolutionRecord]: ...
    def add_edges(self, run_id: int,
                  edges: list[tuple[int, int, float]]) -> None: ...
    def mark_done(self, run_id: int, key: str) -> None: ...
    def edges(self, run_id: int) -> Iterator[tuple[int, int, float]]: ...


def _key_pass(run_id: int, records: Iterable[ResolutionRecord],
              backend: ChunkBackend, on_progress: Progress | None = None) -> None:
    """Pass 1: persist (block_key, record_id) rows; skipped on resume.

    on_progress (§0, 2026-10-04): fired at the same cadence as the progress
    log lines below, with an indeterminate pct (true completion % isn't
    knowable from a streaming pass without a separate count query) -- its
    purpose is purely to act as a liveness heartbeat for the job-status row
    (JobStore.sweep_stale_heartbeat()), not to show real progress. Without
    this, a worker crash during a multi-hundred-thousand-record key pass
    would go undetected for however long `updated_at` is allowed to go
    stale, since nothing else touches the job row during this pass.
    """
    if backend.has_keys(run_id):
        logger.info("key pass skipped (resume) run=%s", run_id)
        return
    if on_progress is not None:
        on_progress("Resolve", 40, "chunked key pass starting")
    batch: list[tuple[str, int]] = []
    total = 0
    next_log_at = _KEY_PASS_LOG_EVERY
    for record in records:
        batch.extend((key, record.record_id) for key in _keys_for(record.text))
        if len(batch) >= 10_000:
            backend.add_members(run_id, batch)
            total += len(batch)
            batch = []
            if total >= next_log_at:
                logger.info("chunked key pass progress run=%s members_persisted=%d", run_id, total)
                raven_log("INFO", "P4", "ingest.resolve.chunked_key_pass_progress key pass progress checkpoint",
                          context={"task_id": run_id, "members_persisted": total, "path": "chunked"})
                if on_progress is not None:
                    on_progress("Resolve", 40, f"chunked key pass: {total} members persisted")
                next_log_at += _KEY_PASS_LOG_EVERY
    if batch:
        backend.add_members(run_id, batch)
        total += len(batch)
    logger.info("chunked key pass done run=%s members_persisted=%d", run_id, total)
