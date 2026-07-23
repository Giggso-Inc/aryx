"""EntityStore.save(): batched Postgres path (no per-row execute loop).

Regression coverage for a real incident: the previous Postgres path
(_save_loop) executed one INSERT per entity plus one more per member, with
no batching — for a large tabular sheet (300K+ rows resolving to that many
individual entities), that was hundreds of thousands of individual DB
round-trips, observed taking hours. _save_batch_postgres fetches all needed
ids in one round-trip (via the aryx_entity BIGSERIAL sequence) then bulk-
inserts entities and members via executemany, mirroring the pattern already
proven for the Oracle path (_save_batch) — cost no longer scales with row
count beyond the executemany payload itself.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from aryx.models import EntityMember, ResolvedEntity
from aryx.store.entity_store import EntityStore


def _make_cursor(fetched_ids: list[int]):
    """A cursor stub: fetchall() returns the id-fetch result once, then
    executemany calls are just recorded."""
    cur = MagicMock()
    cur.fetchall.return_value = [(i,) for i in fetched_ids]
    many_calls: list[list[tuple]] = []
    cur.executemany.side_effect = lambda sql, seq: many_calls.append(list(seq))
    return cur, many_calls


def _make_results(n: int):
    return [
        (ResolvedEntity(ontology_type="T", attributes={"name": str(i)},
                        confidence=1.0, provenance=None, conflicts=None),
         [EntityMember(landed_record_id=i * 10)])
        for i in range(n)
    ]


def _store() -> EntityStore:
    store = EntityStore.__new__(EntityStore)
    store._ws = 1
    store._pool = None
    return store


_DUMMY_SQL = "INSERT INTO t (id, a) VALUES (%s, %s)"


def test_save_batch_postgres_uses_executemany_not_loop() -> None:
    """_save_batch_postgres must call executemany for entities — no per-row
    execute()+fetchone() loop, which is what caused the multi-hour stall."""
    cur, many_calls = _make_cursor([101, 102, 103])
    results = _make_results(3)

    with patch("aryx.store.entity_store.load", return_value=_DUMMY_SQL):
        count = _store()._save_batch_postgres(cur, results)

    assert count == 3
    cur.execute.assert_called_once()  # only the id-fetch, no per-entity execute
    # 1st executemany = entity insert, 2nd = member insert
    assert len(many_calls) == 2
    assert [r[0] for r in many_calls[0]] == [101, 102, 103]


def test_save_batch_postgres_member_rows_use_fetched_ids() -> None:
    cur, many_calls = _make_cursor([201, 202, 203])
    results = _make_results(3)

    with patch("aryx.store.entity_store.load", return_value=_DUMMY_SQL):
        _store()._save_batch_postgres(cur, results)

    member_rows = many_calls[1]
    assert [r[1] for r in member_rows] == [201, 202, 203]


def test_save_batch_postgres_fetches_ids_in_one_round_trip() -> None:
    """The id-fetch must be ONE execute() call regardless of batch size —
    not one per entity."""
    cur, _ = _make_cursor(list(range(1000, 1000 + 500)))
    results = _make_results(500)

    with patch("aryx.store.entity_store.load", return_value=_DUMMY_SQL):
        _store()._save_batch_postgres(cur, results)

    assert cur.execute.call_count == 1
    fetch_sql, fetch_params = cur.execute.call_args[0]
    assert "generate_series" in fetch_sql
    assert fetch_params == (500,)


def test_save_dispatches_to_postgres_batch_by_default() -> None:
    store = _store()
    mock_conn = MagicMock()
    cur, _ = _make_cursor([1, 2])
    mock_conn.cursor.return_value.__enter__.return_value = cur
    mock_conn.cursor.return_value.__exit__.return_value = False
    store._pool = MagicMock()
    store._pool.connection.return_value.__enter__.return_value = mock_conn
    store._pool.connection.return_value.__exit__.return_value = False

    with patch("aryx.store.entity_store.get_settings") as mock_settings, \
         patch.object(EntityStore, "_save_batch_postgres", return_value=2) as mock_pg, \
         patch.object(EntityStore, "_save_batch") as mock_oracle:
        mock_settings.return_value.effective_db_backend.return_value = "postgres"
        n = store.save(_make_results(2))

    assert n == 2
    mock_pg.assert_called_once()
    mock_oracle.assert_not_called()


def test_save_dispatches_to_oracle_batch_when_backend_is_oci() -> None:
    store = _store()
    mock_conn = MagicMock()
    cur, _ = _make_cursor([1, 2])
    mock_conn.cursor.return_value.__enter__.return_value = cur
    mock_conn.cursor.return_value.__exit__.return_value = False
    store._pool = MagicMock()
    store._pool.connection.return_value.__enter__.return_value = mock_conn
    store._pool.connection.return_value.__exit__.return_value = False

    with patch("aryx.store.entity_store.get_settings") as mock_settings, \
         patch.object(EntityStore, "_save_batch_postgres") as mock_pg, \
         patch.object(EntityStore, "_save_batch", return_value=2) as mock_oracle:
        mock_settings.return_value.effective_db_backend.return_value = "oci"
        n = store.save(_make_results(2))

    assert n == 2
    mock_oracle.assert_called_once()
    mock_pg.assert_not_called()


def test_save_returns_zero_for_empty_results_without_touching_db() -> None:
    store = _store()
    store._pool = MagicMock()
    n = store.save([])
    assert n == 0
    store._pool.connection.assert_not_called()
