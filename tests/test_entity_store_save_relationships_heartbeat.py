"""EntityStore.save_relationships(): batching + on_progress heartbeat --
PR review follow-up, 2026-10-04.

Previously a single unbatched executemany for the WHOLE relationship set
gave the caller's job-status row no heartbeat for however long that one
call took. Combined with §0's heartbeat-sweep watchdog
(JobStore.sweep_stale_heartbeat), that silence was long enough to get a
perfectly healthy caller (cpq_ingestion's resolve_and_relate_raw_graph,
after its last tag finishes) killed.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from aryx.models import Relationship
from aryx.store.entity_store import EntityStore

_DUMMY_SQL = "INSERT INTO aryx_relationship (a, b) VALUES (%s, %s)"


def _store_with_mock_pool():
    cur = MagicMock()
    many_calls: list[list[tuple]] = []
    cur.executemany.side_effect = lambda sql, seq: many_calls.append(list(seq))

    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cur)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    pool = MagicMock()
    pool.connection.return_value = conn

    store = EntityStore.__new__(EntityStore)
    store._ws = 1
    store._pool = pool
    return store, many_calls


def _relationships(n: int) -> list[Relationship]:
    return [
        Relationship(source_entity_id=i, target_entity_id=i + 1,
                    name="CONTAINS", confidence=1.0)
        for i in range(n)
    ]


def test_small_relationship_set_is_one_batch_no_progress_needed() -> None:
    store, many_calls = _store_with_mock_pool()
    calls = []

    with patch("aryx.store.entity_store.load", return_value=_DUMMY_SQL):
        store.save_relationships(_relationships(10),
                                 on_progress=lambda s, p, d: calls.append((s, p, d)))

    assert len(many_calls) == 1
    assert len(calls) == 1  # one batch -> one checkpoint


def test_large_relationship_set_is_chunked_into_multiple_executemany_calls() -> None:
    store, many_calls = _store_with_mock_pool()

    with patch("aryx.store.entity_store.load", return_value=_DUMMY_SQL):
        store.save_relationships(_relationships(12_000), batch_size=5000)

    assert len(many_calls) == 3  # 5000 + 5000 + 2000
    assert sum(len(c) for c in many_calls) == 12_000


def test_on_progress_fires_once_per_batch_with_real_done_total() -> None:
    store, _many_calls = _store_with_mock_pool()
    calls = []

    with patch("aryx.store.entity_store.load", return_value=_DUMMY_SQL):
        store.save_relationships(_relationships(12_000), batch_size=5000,
                                 on_progress=lambda s, p, d: calls.append((s, p, d)))

    assert len(calls) == 3
    stages = {c[0] for c in calls}
    assert stages == {"Relate"}
    # pct is REAL done/total here (total known upfront), unlike the
    # indeterminate heartbeats elsewhere in this review round.
    assert calls[0][1] == int(100 * 5000 / 12000)
    assert calls[-1][1] == 100
    assert calls[-1][2] == "12000/12000 relationships saved"


def test_on_progress_none_is_the_default_and_never_raises() -> None:
    store, _many_calls = _store_with_mock_pool()

    with patch("aryx.store.entity_store.load", return_value=_DUMMY_SQL):
        store.save_relationships(_relationships(10))  # no on_progress -- must not raise


def test_empty_relationships_short_circuits_before_touching_the_pool() -> None:
    store, many_calls = _store_with_mock_pool()
    calls = []

    store.save_relationships([], on_progress=calls.append)

    assert many_calls == []
    assert calls == []


def test_on_progress_failure_does_not_abort_or_roll_back_the_save(caplog) -> None:
    """PR review N4 (2026-10-04): on_progress used to be called INSIDE the
    same transaction as the inserts -- a heartbeat failure (e.g. a
    transient job-row update error on a different connection) would
    propagate out of the `with self._pool.connection()` block, rolling
    back every batch already inserted and failing an otherwise-healthy
    save over a purely observational side effect. Must be swallowed and
    logged, with every batch still executed."""
    store, many_calls = _store_with_mock_pool()

    def _flaky_progress(stage, pct, detail):
        raise RuntimeError("job-row update failed (transient)")

    with patch("aryx.store.entity_store.load", return_value=_DUMMY_SQL):
        store.save_relationships(_relationships(12_000), batch_size=5000,
                                 on_progress=_flaky_progress)

    # All 3 batches still ran -- the heartbeat failure never aborted the loop.
    assert len(many_calls) == 3
    assert sum(len(c) for c in many_calls) == 12_000
    assert any("heartbeat failed" in r.message for r in caplog.records)
