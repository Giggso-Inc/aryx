"""Review-flagged gap (2026-08-28, PR #287 review): the touch_channel P4
fix (an O(1) message_count + 1 increment, replacing a full aggregate
rescan) is only safe because ensure_thread_and_user_message/append_
assistant_message now gate the call on the message-insert query's own
genuine-insert flag (`inserted`, aliased from Postgres's `xmax = 0`) --
a retry that hits the ON CONFLICT DO UPDATE branch must NOT increment
message_count a second time for the same message. This was verified live
against a real container during implementation but had no dedicated,
lasting unit test -- a wrong message_count is a subtle, silent bug class
worth a permanent regression test.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from aryx.store.ask_thread_store import AryxAskThreadStore


def _make_mock_pool(fetchone_results):
    """A pool whose every `with pool.connection() as conn, conn.cursor()
    as cur:` block yields the SAME mock cursor, so a single fetchone
    side_effect list can drive the whole call sequence in order."""
    cursor = MagicMock()
    cursor.fetchone.side_effect = fetchone_results

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
    return pool, cursor


def _executed_query_names(cursor):
    """`load(name)` returns the real SQL text, not `name` -- patched to
    return `name` itself so call sites are identifiable by exact query
    key rather than by matching SQL substrings."""
    return [call.args[0] for call in cursor.execute.call_args_list]


def _make_store(pool):
    store = object.__new__(AryxAskThreadStore)
    store._pool = pool
    return store


def test_genuinely_new_message_increments_message_count():
    """inserted=True (a real new gg_messages row, xmax=0) must fire
    touch_channel exactly once."""
    pool, cursor = _make_mock_pool([
        ("shay-ws-1", 1),                      # validate_mapping (ensure_channel)
        ("channel-1",),                        # ensure_channel INSERT
        None,                                  # validate_thread_id_available_or_owned -- no prior owner
        ("thread-1",),                         # ensure_thread
        ("msg-1", 1, True, "hello"),           # insert_message -- inserted=True
    ])
    with patch("aryx.store.ask_thread_store.load", side_effect=lambda name: name):
        store = _make_store(pool)
        result = store.ensure_thread_and_user_message(
            workspace_id=1, shay_workspace_id="shay-ws-1",
            thread_id="thread-1", request_id="req-1", question="hello",
        )

    assert result["request_claimed"] is True
    executed = _executed_query_names(cursor)
    assert executed.count("ask_thread_touch_channel") == 1, (
        f"expected touch_channel to fire exactly once for a genuine new "
        f"message, got {executed.count('ask_thread_touch_channel')} in {executed}"
    )


def test_idempotent_retry_does_not_increment_message_count():
    """inserted=False (the ON CONFLICT DO UPDATE branch fired -- a retry
    of the same request_id, refreshing an existing row) must NOT fire
    touch_channel -- this is the exact double-counting bug a naive +1
    would introduce."""
    pool, cursor = _make_mock_pool([
        ("shay-ws-1", 1),                      # validate_mapping
        ("channel-1",),                        # ensure_channel INSERT
        None,                                  # validate_thread_id_available_or_owned
        ("thread-1",),                         # ensure_thread
        ("msg-1", 1, False, "hello"),          # insert_message -- inserted=False (retry/refresh)
    ])
    with patch("aryx.store.ask_thread_store.load", side_effect=lambda name: name):
        store = _make_store(pool)
        result = store.ensure_thread_and_user_message(
            workspace_id=1, shay_workspace_id="shay-ws-1",
            thread_id="thread-1", request_id="req-1", question="hello",
        )

    assert result["request_claimed"] is True
    executed = _executed_query_names(cursor)
    assert "ask_thread_touch_channel" not in executed, (
        "an idempotent retry (inserted=False) must never increment "
        f"message_count -- touch_channel fired anyway: {executed}"
    )


def test_already_claimed_fallback_path_does_not_increment_message_count():
    """message_row is None on the INSERT (ON CONFLICT's WHERE clause
    didn't match at all) falls back to a plain SELECT of the existing
    row -- that path must also never fire touch_channel, since no new
    row was inserted."""
    pool, cursor = _make_mock_pool([
        ("shay-ws-1", 1),                      # validate_mapping
        ("channel-1",),                        # ensure_channel INSERT
        None,                                  # validate_thread_id_available_or_owned
        ("thread-1",),                         # ensure_thread
        None,                                  # insert_message -- no row returned at all
        ("msg-1", 1, False, "hello"),          # fallback select_request_message
    ])
    with patch("aryx.store.ask_thread_store.load", side_effect=lambda name: name):
        store = _make_store(pool)
        result = store.ensure_thread_and_user_message(
            workspace_id=1, shay_workspace_id="shay-ws-1",
            thread_id="thread-1", request_id="req-1", question="hello",
        )

    assert result["request_claimed"] is False
    executed = _executed_query_names(cursor)
    assert "ask_thread_touch_channel" not in executed, (
        f"the already-claimed fallback path must never increment "
        f"message_count -- touch_channel fired anyway: {executed}"
    )


def test_append_assistant_message_new_row_increments_message_count():
    pool, cursor = _make_mock_pool([
        ("msg-2", 2, True, "the answer"),      # insert_message -- inserted=True
        None,                                  # update_request_status (no fetchone consumed, placeholder)
    ])
    with patch("aryx.store.ask_thread_store.load", side_effect=lambda name: name):
        store = _make_store(pool)
        store.append_assistant_message(
            thread_id="thread-1", channel_id="channel-1", request_id="req-1",
            answer="the answer", result={},
        )

    executed = _executed_query_names(cursor)
    assert executed.count("ask_thread_touch_channel") == 1


def test_append_assistant_message_retry_does_not_increment_message_count():
    """A retry that hits the ON CONFLICT DO UPDATE branch (e.g.
    refreshing a previously-failed response) must not double-count."""
    pool, cursor = _make_mock_pool([
        ("msg-2", 2, False, "the answer"),     # insert_message -- inserted=False (refresh)
        None,
    ])
    with patch("aryx.store.ask_thread_store.load", side_effect=lambda name: name):
        store = _make_store(pool)
        store.append_assistant_message(
            thread_id="thread-1", channel_id="channel-1", request_id="req-1",
            answer="the answer", result={},
        )

    executed = _executed_query_names(cursor)
    assert "ask_thread_touch_channel" not in executed
