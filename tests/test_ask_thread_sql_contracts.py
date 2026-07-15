"""SQL contract checks for Shay-message-backed Ask threads."""

from __future__ import annotations

from pathlib import Path


QUERY_DIR = Path(__file__).resolve().parents[1] / "src" / "aryx" / "queries"


def _sql(name: str) -> str:
    return (QUERY_DIR / f"{name}.sql").read_text(encoding="utf-8")


def test_ask_thread_insert_message_conflict_preserves_existing_user_prompt():
    sql = _sql("ask_thread_insert_message")

    assert "WHEN gg_messages.message_type = 'user' THEN gg_messages.content" in sql


def test_ask_thread_history_only_reads_visible_messages():
    sql = _sql("ask_thread_select_history")

    assert "is_visible = TRUE" in sql


def test_ask_thread_cached_response_only_reads_visible_messages():
    sql = _sql("ask_thread_select_cached_response")

    assert "gg_messages.is_visible = TRUE" in sql


def test_ask_thread_list_messages_exposes_request_id_for_recovery():
    sql = _sql("ask_thread_list_messages")

    assert "request_id::text" in sql
