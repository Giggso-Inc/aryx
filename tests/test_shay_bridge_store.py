"""Unit tests for Shay bridge store helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_conversation_history_expands_each_saved_turn_pair():
    from aryx.store.shay_bridge_store import ShayBridgeStore

    store = object.__new__(ShayBridgeStore)
    store.list_chat_turns = MagicMock(
        return_value=[
            {"question": "First question", "answer": "First answer"},
            {"question": "Second question", "answer": "Second answer"},
        ]
    )

    history = store.conversation_history("thread-1", limit_pairs=2)

    store.list_chat_turns.assert_called_once_with("thread-1", limit=2)
    assert history == [
        {"role": "user", "text": "First question"},
        {"role": "assistant", "text": "First answer"},
        {"role": "user", "text": "Second question"},
        {"role": "assistant", "text": "Second answer"},
    ]


def test_sync_datasource_updates_existing_mapping_and_datasource():
    from aryx.store.shay_bridge_store import ShayBridgeStore

    cursor = MagicMock()
    cursor.fetchone.side_effect = [
        ("shay-ds-1", 44, "ws-1", 7, "job-old"),
        ("shay-ds-1", 44, "ws-1", 7, "job-new"),
    ]
    cursor_cm = MagicMock()
    cursor_cm.__enter__.return_value = cursor
    cursor_cm.__exit__.return_value = False

    conn = MagicMock()
    conn.cursor.return_value = cursor_cm
    conn_cm = MagicMock()
    conn_cm.__enter__.return_value = conn
    conn_cm.__exit__.return_value = False

    pool = MagicMock()
    pool.connection.return_value = conn_cm

    datasource_store = MagicMock()
    datasource_store.update.return_value = {"id": 44}

    with (
        patch("aryx.store.shay_bridge_store.get_pool", return_value=pool),
        patch("aryx.store.shay_bridge_store.DatasourceStore", return_value=datasource_store),
    ):
        store = ShayBridgeStore("postgresql://example")
        store.get_workspace_mapping = MagicMock(
            return_value={"shay_workspace_id": "ws-1", "aryx_workspace_id": 7}
        )

        result = store.sync_datasource(
            shay_datasource_id="shay-ds-1",
            shay_workspace_id="ws-1",
            name="Accounts",
            kind="postgresql",
            config={"database": "analytics"},
            secret=None,
            ingest_job_id="job-new",
        )

    datasource_store.update.assert_called_once_with(
        44,
        name="Accounts",
        kind="postgresql",
        config={"database": "analytics"},
        secret=None,
    )
    assert result == {
        "shay_datasource_id": "shay-ds-1",
        "aryx_datasource_id": 44,
        "shay_workspace_id": "ws-1",
        "aryx_workspace_id": 7,
        "ingest_job_id": "job-new",
        "created": False,
    }
