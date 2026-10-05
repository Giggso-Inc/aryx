"""resolve()'s on_block_progress heartbeat -- live incident, 2026-10-05.

A real CPQ confirm job was killed by JobStore.sweep_stale_heartbeat's
20-minute WORKER_LOST timeout while it was still actively resolving: the
heartbeat checkpoint (on_block_progress) only fired every _PROGRESS_EVERY
(25) blocks, and a run of unusually large near-duplicate blocks took over
22 minutes to clear fewer than 25 blocks -- block count is not a reliable
proxy for wall-clock time. resolution/run.py now also fires on_block_progress
whenever _PROGRESS_MAX_SECONDS has elapsed since the last emission,
regardless of block count, closing that gap.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from aryx.models import ResolutionRecord
from aryx.resolution.run import resolve


def _fixture(n_clusters: int, size: int = 2) -> list[ResolutionRecord]:
    """n_clusters distinct blocking groups of `size` near-duplicate records
    each -- enough multi-member blocks to exercise the pair-scoring loop
    on_block_progress lives in (singleton blocks are skipped entirely)."""
    records, rid = [], 0
    for c in range(n_clusters):
        name = f"unique{c:02d} fixture entity"
        for _ in range(size):
            records.append(ResolutionRecord(record_id=rid, text=name,
                                            payload={"name": name}))
            rid += 1
    return records


def _broker_no_embeddings() -> MagicMock:
    """String-only scoring fallback -- no real network calls."""
    broker = MagicMock()
    broker.embed.side_effect = RuntimeError("no embeddings in this test")
    return broker


def test_progress_fires_only_at_25_blocks_or_last_when_clock_is_fast() -> None:
    """Baseline (no regression): with a fast-moving clock (no elapsed time
    between blocks), progress only fires per _PROGRESS_EVERY/at the end --
    confirms the time-based path does NOT fire spuriously on every block."""
    records = _fixture(n_clusters=3)  # 3 multi-member blocks, well under 25
    broker = _broker_no_embeddings()
    calls: list[tuple[int, int]] = []

    resolve(records, broker, "Thing",
            on_block_progress=lambda done, total: calls.append((done, total)))

    # Only the final-block case should have fired (well under
    # _PROGRESS_EVERY=25 total blocks, and the real clock barely advances
    # within this fast in-memory test) -- exactly one call, for the last block.
    assert len(calls) == 1
    done, total = calls[0]
    assert done == total


def test_progress_fires_on_time_ceiling_even_mid_run_when_blocks_are_slow() -> None:
    """Regression guard: simulate a slow block (wall-clock-wise) by making
    time.monotonic() jump past _PROGRESS_MAX_SECONDS on every call -- the
    very first (non-final, non-25th) block must still trigger a heartbeat,
    which is exactly what the pre-fix code could never do for a run of
    expensive blocks under 25."""
    records = _fixture(n_clusters=3)  # several multi-member blocks, all < 25
    broker = _broker_no_embeddings()
    calls: list[tuple[int, int]] = []

    # Monotonically increasing fake clock, +120s on every read -- guarantees
    # _PROGRESS_MAX_SECONDS (60s) has elapsed by the time block 1 finishes.
    fake_now = [0.0]

    def _fake_monotonic() -> float:
        fake_now[0] += 120.0
        return fake_now[0]

    with patch("aryx.resolution.run.time.monotonic", side_effect=_fake_monotonic):
        resolve(records, broker, "Thing",
                on_block_progress=lambda done, total: calls.append((done, total)))

    assert calls, "expected at least one heartbeat"
    first_done, total = calls[0]
    assert first_done == 1 < total, (
        "expected a heartbeat after block 1 due to the time ceiling, even "
        "though block 1 is neither the 25th block nor the last one -- got "
        f"first call {calls[0]}"
    )
