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
    assert first_done < total, (
        "expected an early heartbeat (embedding-prefetch or mid-block "
        "time ceiling) well before the run finishes -- got first call "
        f"{calls[0]}, which looks like only the final checkpoint fired"
    )


def test_progress_fires_during_embedding_prefetch_before_any_pair_is_scored() -> None:
    """Regression guard, isolated to the embedding-prefetch loop (PR review
    follow-up): the prefetch (ThreadPoolExecutor + as_completed) had ZERO
    on_block_progress calls anywhere in it, even though this module's own
    docstring says embedding is ~99% of resolve()'s wall-clock time on a
    realistic dataset -- a large tag could sit there silently for many
    minutes.

    Isolates the prefetch specifically from the per-pair mid-block check
    (both can independently fire a heartbeat with done=0, which would
    otherwise be ambiguous): the fake clock only advances inside
    broker.embed() -- called exclusively during the prefetch, never again
    during the pair-scoring loop below it (embeddings are cached by then).
    So ANY heartbeat observed before the run's final checkpoint can only
    have come from the prefetch loop's own check.
    """
    records = _fixture(n_clusters=3)  # several multi-member blocks -> several embed() calls during prefetch
    broker = MagicMock()
    fake_now = [0.0]

    def _embed_side_effect(_texts):
        fake_now[0] += 70.0  # only source of elapsed time in this test
        raise RuntimeError("no embeddings in this test")  # falls back to string-only scoring

    broker.embed.side_effect = _embed_side_effect
    calls: list[tuple[int, int]] = []

    with patch("aryx.resolution.run.time.monotonic", side_effect=lambda: fake_now[0]):
        resolve(records, broker, "Thing",
                on_block_progress=lambda done, total: calls.append((done, total)))

    assert calls, "expected a heartbeat during the embedding prefetch"
    first_done, total = calls[0]
    assert first_done == 0 < total, (
        f"expected the first heartbeat to fire mid-prefetch (done=0) -- got {calls[0]}"
    )


def test_progress_fires_mid_block_for_a_single_large_block_of_slow_pairs() -> None:
    """Regression guard, isolated to the per-pair check inside the block
    loop (PR review follow-up): max_pairs_per_block defaults to 500 and
    _route_pair can trigger an LLM adjudication call per pair, so a SINGLE
    block can run for tens of minutes -- past the end-of-block-only check
    this fix originally had, which would never re-check until that one
    block finally finished.

    One multi-member block (one embed() call, cheap/instant) with several
    members -- several pairs -- so the per-pair loop runs more than once.
    The fake clock only advances inside score_pair's module-level
    monotonic() reads are NOT touched; instead this patches
    time.monotonic() globally with a small per-call increment, well under
    one full block's worth of calls but enough to cross the threshold
    partway through the pair loop, proving the mid-block check (not just
    the end-of-block one) is what fired.
    """
    records = _fixture(n_clusters=1, size=6)  # one block, C(6,2)=15 pairs
    broker = _broker_no_embeddings()
    calls: list[tuple[int, int]] = []

    # +10s per read: several reads needed to cross the 60s ceiling, so the
    # FIRST heartbeat can only come from repeated per-pair checks within
    # this one block, not a single end-of-block check.
    fake_now = [0.0]

    def _fake_monotonic() -> float:
        fake_now[0] += 10.0
        return fake_now[0]

    with patch("aryx.resolution.run.time.monotonic", side_effect=_fake_monotonic):
        resolve(records, broker, "Thing",
                on_block_progress=lambda done, total: calls.append((done, total)))

    assert calls, "expected at least one heartbeat"
    # done=0 means "block_idx 0, not yet complete" -- only the mid-block
    # per-pair check reports that; the end-of-block check for the (only,
    # first) block would report done=1 (block_idx + 1).
    assert any(done == 0 for done, _total in calls), (
        f"expected a mid-block (done=0) heartbeat before the block finished -- got {calls}"
    )
