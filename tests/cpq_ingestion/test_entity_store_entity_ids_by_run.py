"""EntityStore.entity_ids_by_run -- the one DB-touching lookup the raw-graph
resolve/relate bridge needs: recovering "which entity did this landed
record resolve into" after resolve/save has already run, since save()
itself only returns a count. Lives in entity_store.py (not cpq_ingestion)
because it reads generic aryx_landed_record/aryx_entity_member tables, not
anything cpq_ingestion-specific -- covered here since it exists for this
feature.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from aryx.store.entity_store import EntityStore


def _store_with_rows(rows: list[tuple[str, int]]) -> EntityStore:
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = rows
    mock_cursor.__enter__.return_value = mock_cursor
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.__enter__.return_value = mock_conn
    mock_pool = MagicMock()
    mock_pool.connection.return_value = mock_conn
    with patch("aryx.store.entity_store.get_pool", return_value=mock_pool):
        return EntityStore("dsn://irrelevant", workspace_id=7)


def test_entity_ids_by_run_returns_source_record_id_to_entity_id_mapping():
    store = _store_with_rows([("accounts:0", 100), ("accounts:1", 101)])

    result = store.entity_ids_by_run(42)

    assert result == {"accounts:0": 100, "accounts:1": 101}


def test_entity_ids_by_run_empty_result_returns_empty_dict():
    store = _store_with_rows([])

    assert store.entity_ids_by_run(42) == {}


def test_entity_ids_by_run_passes_run_id_and_workspace_id_to_query():
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = []
    mock_cursor.__enter__.return_value = mock_cursor
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.__enter__.return_value = mock_conn
    mock_pool = MagicMock()
    mock_pool.connection.return_value = mock_conn
    with patch("aryx.store.entity_store.get_pool", return_value=mock_pool):
        store = EntityStore("dsn://irrelevant", workspace_id=7)
        store.entity_ids_by_run(42)

    args, _ = mock_cursor.execute.call_args
    assert args[1] == (42, 7)


# ── EntityStore.delete_entities -- bulk cleanup for a cancelled resolve/
# relate attempt (PR #429 review N1, M1's own cleanup needed one round-trip
# per id, undermining the "cancel should be prompt" point of this feature) ──

def test_delete_entities_sends_one_delete_for_the_whole_id_list():
    mock_cursor = MagicMock()
    mock_cursor.rowcount = 3
    mock_cursor.__enter__.return_value = mock_cursor
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.__enter__.return_value = mock_conn
    mock_pool = MagicMock()
    mock_pool.connection.return_value = mock_conn
    with patch("aryx.store.entity_store.get_pool", return_value=mock_pool):
        store = EntityStore("dsn://irrelevant", workspace_id=7)
        removed = store.delete_entities([100, 101, 102])

    assert removed == 3
    mock_cursor.execute.assert_called_once()
    args, _ = mock_cursor.execute.call_args
    assert args[1] == {"workspace_id": 7, "entity_ids": [100, 101, 102]}


def test_delete_entities_empty_list_is_a_noop():
    mock_pool = MagicMock()
    with patch("aryx.store.entity_store.get_pool", return_value=mock_pool):
        store = EntityStore("dsn://irrelevant", workspace_id=7)
        removed = store.delete_entities([])

    assert removed == 0
    mock_pool.connection.assert_not_called()


def test_delete_entities_chunks_large_id_lists(monkeypatch):
    """PR #429 review N1 (round 2): an unbounded id list means one huge
    array bind and one long-running DELETE for the largest attempts this
    PR's cancellation support targets -- chunked so a slow cleanup is
    bounded per-chunk, not one unbreakable statement."""
    mock_cursor = MagicMock()
    mock_cursor.rowcount = 2
    mock_cursor.__enter__.return_value = mock_cursor
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.__enter__.return_value = mock_conn
    mock_pool = MagicMock()
    mock_pool.connection.return_value = mock_conn
    with patch("aryx.store.entity_store.get_pool", return_value=mock_pool):
        store = EntityStore("dsn://irrelevant", workspace_id=7)
        monkeypatch.setattr(store, "_DELETE_CHUNK_SIZE", 2)
        removed = store.delete_entities([1, 2, 3, 4, 5])

    assert removed == 6  # 3 chunks * rowcount=2 each (stubbed, not realistic per-chunk)
    assert mock_cursor.execute.call_count == 3
    chunks = [call.args[1]["entity_ids"] for call in mock_cursor.execute.call_args_list]
    assert chunks == [[1, 2], [3, 4], [5]]
