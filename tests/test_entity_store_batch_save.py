"""Regression coverage for EntityStore.save_returning_ids()'s batched writes.

Before this fix, save_returning_ids() did one cur.execute() per entity, one
more per member, and one more per conflict — N x (1 + M + C) round trips to
Postgres for N resolved entities. On a file with a few thousand records this
was the dominant cost of ingestion. The fix pre-fetches N sequence values in
one round trip, then writes entities/members/conflicts via one executemany()
each — a constant number of round trips regardless of batch size.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from aryx.models import EntityMember, ResolvedEntity
from aryx.store.entity_store import EntityStore


def _make_store(fetchall_ids):
    """Build an EntityStore with a mocked pool/connection/cursor.

    fetchall_ids: the rows the id-prefetch SELECT should return, e.g.
    [(101,), (102,), (103,)].
    """
    store = EntityStore.__new__(EntityStore)
    store._ws = 1

    cur = MagicMock()
    cur.fetchall.return_value = fetchall_ids
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    pool = MagicMock()
    pool.connection.return_value.__enter__.return_value = conn
    store._pool = pool
    return store, cur


def _entity(otype="Widget", attrs=None, confidence=0.9, conflicts=None):
    return ResolvedEntity(ontology_type=otype, attributes=attrs or {"name": "x"},
                          confidence=confidence, provenance=None, conflicts=conflicts)


class TestBatchedSave:
    def test_round_trip_count_is_constant_not_proportional_to_batch_size(self):
        """The whole point of the fix: 1 id-prefetch + up to 3 executemany
        calls, regardless of whether there are 1 or 100 entities."""
        n = 100
        ids = [(1000 + i,) for i in range(n)]
        store, cur = _make_store(ids)
        results = [
            (_entity(), [EntityMember(landed_record_id=i)])
            for i in range(n)
        ]

        returned_ids = store.save_returning_ids(results)

        assert returned_ids == [row[0] for row in ids]
        # Exactly one plain execute() for the id-prefetch SELECT.
        assert cur.execute.call_count == 1
        # Entities + members = 2 executemany calls (no conflicts here).
        assert cur.executemany.call_count == 2

    def test_ids_returned_in_input_order(self):
        store, cur = _make_store([(5,), (6,), (7,)])
        results = [(_entity(otype=t), []) for t in ("A", "B", "C")]

        returned_ids = store.save_returning_ids(results)

        assert returned_ids == [5, 6, 7]
        entity_rows = cur.executemany.call_args_list[0].args[1]
        # Row order must match the pre-fetched id order, and each row's
        # ontology_type must correspond to the same-position input entity.
        assert [row[0] for row in entity_rows] == [5, 6, 7]
        assert [row[2] for row in entity_rows] == ["A", "B", "C"]

    def test_conflicts_batch_only_written_when_present(self):
        store, cur = _make_store([(1,)])
        conflicts = [{"attribute": "name", "winning_value": "A",
                     "losing_values": ["B"], "strategy": "most_common"}]
        results = [(_entity(conflicts=conflicts), [EntityMember(landed_record_id=1)])]

        store.save_returning_ids(results)

        # entities + members + conflicts, all non-empty = 3 executemany calls.
        assert cur.executemany.call_count == 3

    def test_no_conflicts_skips_that_executemany_call(self):
        store, cur = _make_store([(1,)])
        results = [(_entity(conflicts=None), [])]

        store.save_returning_ids(results)

        # entities + members only (members list is empty too, but the
        # member executemany call still fires with an empty list guarded
        # out — conflicts specifically must be skipped when there are none).
        calls = cur.executemany.call_count
        assert calls <= 2

    def test_empty_results_short_circuits_without_any_db_call(self):
        store, cur = _make_store([])

        returned_ids = store.save_returning_ids([])

        assert returned_ids == []
        cur.execute.assert_not_called()
        cur.executemany.assert_not_called()
