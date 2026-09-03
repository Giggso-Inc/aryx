"""Oracle-native equivalent of ask_thread_insert_message.sql's retry-safe upsert.

Split out of `store/ask_thread_store.py` (Raven Style Compliance Plan,
Phase 2a, 2026-09-03).
"""
from __future__ import annotations

from typing import Any

from aryx.queries import load
from aryx.store.ask_thread_helpers import _as_json


def _insert_message_oracle(cur: Any, params: tuple[Any, ...]) -> tuple[str, int, bool, str] | None:
    """Oracle-native equivalent of ask_thread_insert_message.sql's retry-safe upsert.

    Postgres does this in one statement (INSERT ... ON CONFLICT ... DO UPDATE
    ... WHERE <retry-safety CASE logic> ... RETURNING id, sequence_number,
    (xmax = 0) AS inserted, content), using `xmax = 0` to tell the caller
    whether it inserted or updated. Oracle has no `xmax` equivalent -- this
    expresses the same decision as explicit Python branches instead: lock the
    thread row (serializes sequence_number assignment), check for an existing
    row under that lock, then either insert fresh or apply the same
    conditional-overwrite rules as a plain UPDATE.

    Returns a 4-tuple matching the Postgres RETURNING shape -- (id,
    sequence_number, inserted, content) -- if inserted or safely updated.
    `inserted` is True only on the genuine-insert branch below -- callers
    use it (ensure_thread_and_user_message/append_assistant_message's
    newly_inserted) to gate ask_thread_touch_channel so a retry that hits
    the update branch doesn't double-count message_count. Returns None if
    an existing row must not be overwritten (caller then loads the existing
    row via ask_thread_select_request_message, exactly like the Postgres
    path).
    """
    (thread_id, message_id, content, message_type, _thread_id_again, request_id,
     is_ai_processed, ai_provider, ai_model, ai_processing_time,
     metadata, citations, usage) = params
    # gg_messages.is_ai_processed is NUMBER(0/1) (SQLAlchemy's Oracle Boolean),
    # but oracle_pool.py's _unwrap_params() converts every Python bool to
    # 'Y'/'N' for aryx_*'s own CHAR(1) convention -- wrong for this column,
    # so convert explicitly here instead of letting that happen.
    is_ai_processed = 1 if is_ai_processed else 0

    cur.execute(load("ask_thread_lock_thread"), (thread_id,))
    cur.fetchone()

    cur.execute(
        load("ask_thread_select_existing_message"),
        (thread_id, request_id, message_type),
    )
    existing = cur.fetchone()

    if existing is None:
        cur.execute(load("ask_thread_next_sequence"), (thread_id,))
        next_seq = int(cur.fetchone()[0])
        cur.execute(
            load("ask_thread_insert_message_oracle"),
            (message_id, content, message_type, thread_id, request_id,
             is_ai_processed, ai_provider, ai_model, ai_processing_time,
             next_seq, metadata, citations, usage),
        )
        return (message_id, next_seq, True, content)

    existing_id, existing_seq, existing_content, existing_metadata_raw, existing_updated_at = existing

    if message_type != "user":
        # Assistant/system messages always overwrite -- no retry-safety gate.
        cur.execute(
            load("ask_thread_update_message_oracle"),
            (content, is_ai_processed, ai_provider, ai_model, ai_processing_time,
             metadata, citations, usage, existing_id),
        )
        return (str(existing_id), int(existing_seq), False, content)

    # User-message retry safety: only overwrite if it's the exact same
    # question AND the prior attempt genuinely needs retrying.
    if existing_content != content:
        return None
    existing_metadata = _as_json(existing_metadata_raw) or {}
    status = existing_metadata.get("request_status")
    should_overwrite = False
    if status == "failed":
        should_overwrite = True
    elif status is None:
        cur.execute(load("ask_thread_has_failed_response"), (thread_id, request_id))
        should_overwrite = cur.fetchone() is not None
    elif status == "in_progress" and existing_updated_at is not None:
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        updated = existing_updated_at
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
        should_overwrite = (now - updated) > timedelta(minutes=20)
    if not should_overwrite:
        return None
    cur.execute(
        load("ask_thread_update_message_oracle"),
        (content, is_ai_processed, ai_provider, ai_model, ai_processing_time,
         metadata, citations, usage, existing_id),
    )
    return (str(existing_id), int(existing_seq), False, content)
