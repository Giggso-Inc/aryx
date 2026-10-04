"""§5 of docs/ingestion/CPQ_XML_CONFIRM_RESOLVE_PERFORMANCE_ISSUES_2026-10-04.md:
aryx_entity_member rows were never cleaned up by delete_entity(),
delete_entities(), or delete_entities_by_type() -- a deleted entity left
permanent orphan member rows pointing at a now-nonexistent entity_id.
Fixed by deleting member rows first, in the same transaction, before the
entity row(s) themselves (member deletion must go first: Postgres's
aryx_entity_member.entity_id has a plain FK to aryx_entity with no
ON DELETE CASCADE, so deleting the entity row first would raise a
foreign-key violation while member rows for it still exist).
delete_entities_by_type()'s own coverage lives in
test_ontology_delete_type_oracle_backend_2026_09_25.py.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from aryx.store.entity_store import EntityStore


def _make_store():
    store = EntityStore.__new__(EntityStore)
    store._ws = 1
    store._pool = MagicMock()
    cur = MagicMock()
    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cur)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    store._pool.connection.return_value = conn
    return store, cur


def test_delete_entity_deletes_members_before_the_entity_row():
    store, cur = _make_store()
    cur.rowcount = 1
    with patch("aryx.store.entity_store.load", side_effect=lambda name: name):
        removed = store.delete_entity(42)

    assert removed is True
    assert cur.execute.call_count == 2
    members_call, entity_call = cur.execute.call_args_list
    assert members_call.args[0] == "delete_entity_members_by_id"
    assert members_call.args[1] == (1, 42)
    assert entity_call.args[0] == "delete_entity_row"
    assert entity_call.args[1] == (42, 1)


def test_delete_entity_returns_false_when_nothing_removed():
    store, cur = _make_store()
    cur.rowcount = 0
    with patch("aryx.store.entity_store.load", side_effect=lambda name: name):
        removed = store.delete_entity(999)

    assert removed is False


def test_delete_entities_deletes_members_before_entities_per_chunk():
    store, cur = _make_store()
    cur.rowcount = 2
    with patch("aryx.store.entity_store.load", side_effect=lambda name: name):
        removed = store.delete_entities([1, 2])

    assert removed == 2
    assert cur.execute.call_count == 2
    members_call, entities_call = cur.execute.call_args_list
    assert members_call.args[0] == "delete_entity_members_by_ids"
    assert members_call.args[1] == {"workspace_id": 1, "entity_ids": [1, 2]}
    assert entities_call.args[0] == "delete_entities_by_ids"
    assert entities_call.args[1] == {"workspace_id": 1, "entity_ids": [1, 2]}


def test_delete_entities_empty_list_does_nothing():
    store, cur = _make_store()
    with patch("aryx.store.entity_store.load", side_effect=lambda name: name):
        removed = store.delete_entities([])

    assert removed == 0
    cur.execute.assert_not_called()


def test_delete_entities_chunks_members_and_entities_together():
    """Each chunk must delete its own members before its own entities --
    not all members up front, then all entities (which would still leave
    a FK-violation window on Postgres for every chunk after the first)."""
    store, cur = _make_store()
    cur.rowcount = 1
    store._DELETE_CHUNK_SIZE = 2
    with patch("aryx.store.entity_store.load", side_effect=lambda name: name):
        store.delete_entities([1, 2, 3])

    query_names = [c.args[0] for c in cur.execute.call_args_list]
    assert query_names == [
        "delete_entity_members_by_ids", "delete_entities_by_ids",  # chunk [1, 2]
        "delete_entity_members_by_ids", "delete_entities_by_ids",  # chunk [3]
    ]
    first_chunk_ids = cur.execute.call_args_list[0].args[1]["entity_ids"]
    second_chunk_ids = cur.execute.call_args_list[2].args[1]["entity_ids"]
    assert first_chunk_ids == [1, 2]
    assert second_chunk_ids == [3]
