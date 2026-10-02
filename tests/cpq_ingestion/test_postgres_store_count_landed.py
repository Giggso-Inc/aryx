"""PostgresStore.count_landed -- added for cpq_ingestion's csv_land.py,
which has no resolve/project stage of its own to report a row count from
(discover() only returns a run_id). Lives in postgres_store.py (not
cpq_ingestion) since it reads the generic aryx_landed_record table.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from aryx.store.postgres_store import PostgresStore


def _store_with_count(count: int) -> PostgresStore:
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = (count,)
    mock_cursor.__enter__.return_value = mock_cursor
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.__enter__.return_value = mock_conn
    mock_pool = MagicMock()
    mock_pool.connection.return_value = mock_conn
    with patch("aryx.store.postgres_store.get_pool", return_value=mock_pool):
        store = PostgresStore("dsn://irrelevant", workspace_id=7)
    return store, mock_cursor


def test_count_landed_returns_the_row_count():
    store, _ = _store_with_count(5)
    assert store.count_landed(run_id=42) == 5


def test_count_landed_zero_rows():
    store, _ = _store_with_count(0)
    assert store.count_landed(run_id=42) == 0


def test_count_landed_passes_run_id_and_workspace_id_to_query():
    store, cursor = _store_with_count(3)
    store.count_landed(run_id=42)
    args, _ = cursor.execute.call_args
    assert args[1] == (42, 7)


def test_count_landed_no_row_returned_defaults_to_zero():
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = None
    mock_cursor.__enter__.return_value = mock_cursor
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.__enter__.return_value = mock_conn
    mock_pool = MagicMock()
    mock_pool.connection.return_value = mock_conn
    with patch("aryx.store.postgres_store.get_pool", return_value=mock_pool):
        store = PostgresStore("dsn://irrelevant", workspace_id=1)

    assert store.count_landed(run_id=1) == 0
