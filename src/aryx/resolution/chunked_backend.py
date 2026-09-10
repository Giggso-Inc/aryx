"""Chunk-backend protocol + the key pass (streaming block-key persistence).

Split out of `resolution/chunked.py` (Raven Style Compliance Plan, Phase
2b, 2026-09-03). Zero patch risk — confirmed via grep (neither calls
`get_settings()`/`_materialize`, the two patched names in this module).
"""
from __future__ import annotations

import logging
from collections.abc import Iterable, Iterator
from typing import Protocol

from aryx.models import ResolutionRecord
from aryx.resolution.blocking import _keys_for

logger = logging.getLogger(__name__)


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
              backend: ChunkBackend) -> None:
    """Pass 1: persist (block_key, record_id) rows; skipped on resume."""
    if backend.has_keys(run_id):
        logger.info("key pass skipped (resume) run=%s", run_id)
        return
    batch: list[tuple[str, int]] = []
    for record in records:
        batch.extend((key, record.record_id) for key in _keys_for(record.text))
        if len(batch) >= 10_000:
            backend.add_members(run_id, batch)
            batch = []
    if batch:
        backend.add_members(run_id, batch)
