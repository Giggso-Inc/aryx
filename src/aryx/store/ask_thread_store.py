"""Persistence for Aryx Ask conversations stored as Shay threads/messages."""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

from psycopg.types.json import Json

from aryx.config import get_settings
from aryx.queries import load
from aryx.store.ask_thread_contract import (
    REQUEST_STATUS_COMPLETED,
    REQUEST_STATUS_FAILED,
    REQUEST_STATUS_IN_PROGRESS,
    message_insert_params,
)
from aryx.store.pool import get_pool

ASK_CHANNEL_NAME = "__aryx_ask__"
ASK_CHANNEL_DESCRIPTION = "Hidden Aryx Ask conversation channel"


def _as_int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _as_json(value: Any) -> Any:
    """Parse a JSON column value that may arrive as a string or already-parsed.

    Postgres JSONB columns come back as dict/list (psycopg auto-decodes).
    Shay's gg_* tables store the same data as CLOB on Oracle (no native JSON
    type there), so oracledb returns plain text -- this normalizes both to
    the same Python shape the caller expects.
    """
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            return value
    return value


def normalize_grounding_citations(grounding: Any) -> list[dict[str, Any]]:
    """Return frontend citation objects from the grounding contract."""
    if not isinstance(grounding, dict):
        return []
    raw_citations = grounding.get("citations")
    if not isinstance(raw_citations, list):
        return []

    citations = []
    for index, citation in enumerate(raw_citations):
        if not isinstance(citation, dict):
            continue
        label = citation.get("label") or citation.get("entity_name")
        if not isinstance(label, str) or not label.strip():
            continue
        citations.append({
            "entity_id": _as_int(
                citation.get("entity_id"),
                _as_int(citation.get("marker"), index),
            ),
            "label": label,
            "type": citation.get("type") or citation.get("entity_type"),
        })
    return citations


def _is_oracle_backend() -> bool:
    return get_settings().effective_db_backend() == "oci"


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
    sequence_number, inserted, content) -- if inserted or safely updated
    (`inserted` is always False here since callers never read it; kept only
    for shape parity with ask_thread_select_request_message.sql's fallback
    row, which callers *do* index positionally). Returns None if an existing
    row must not be overwritten (caller then loads the existing row via
    ask_thread_select_request_message, exactly like the Postgres path).
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
        return (message_id, next_seq, False, content)

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


def normalize_thread_title(question: str, max_len: int = 80) -> str:
    """Return the deterministic first-prompt title for an Ask thread."""
    title = re.sub(r"\s+", " ", question.strip())
    if not title:
        return "New chat"
    if len(title) <= max_len:
        return title
    return title[: max_len - 1].rstrip() + "..."


class AryxAskThreadStore:
    """CRUD helpers for the hidden Shay channel used by Aryx Ask."""

    def __init__(self, dsn: str) -> None:
        self._pool = get_pool(dsn)

    def close(self) -> None:
        """No-op: shared pool lifecycle is managed globally."""

    def validate_mapping(self, workspace_id: int, shay_workspace_id: str) -> None:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(load("ask_thread_select_mapping"), (shay_workspace_id, workspace_id))
            row = cur.fetchone()
        if row is None:
            raise ValueError("Shay workspace is not mapped to this Aryx workspace")

    def validate_thread(
        self,
        workspace_id: int,
        shay_workspace_id: str,
        thread_id: str,
    ) -> None:
        self.validate_mapping(workspace_id, shay_workspace_id)
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                load("ask_thread_select_thread_scope"),
                (thread_id, shay_workspace_id, ASK_CHANNEL_NAME),
            )
            row = cur.fetchone()
        if row is None:
            raise ValueError("Ask thread does not belong to this Shay workspace")

    def validate_thread_id_available_or_owned(
        self,
        shay_workspace_id: str,
        thread_id: str,
    ) -> None:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(load("ask_thread_select_thread_owner"), (thread_id,))
            row = cur.fetchone()
        if row is None:
            return
        # bool(row[3]) not `is True` -- Postgres returns a real bool, Oracle's
        # gg_channels.is_* convention is NUMBER(0/1) and 1 is not True by
        # identity (1 is True == False in Python). bool() is correct for both.
        if row[1] == shay_workspace_id and row[2] == ASK_CHANNEL_NAME and bool(row[3]):
            return
        raise ValueError("Ask thread id is already used outside this Shay workspace")

    def ensure_channel(self, shay_workspace_id: str, workspace_id: int) -> str:
        self.validate_mapping(workspace_id, shay_workspace_id)
        channel_id = str(uuid.uuid4())
        settings = {
            "aryx_hidden": True,
            "aryx_feature": "ask",
            "aryx_workspace_id": int(workspace_id),
        }
        tags = {"system": "aryx", "feature": "ask"}
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                load("ask_thread_ensure_channel"),
                (
                    shay_workspace_id,
                    channel_id,
                    ASK_CHANNEL_NAME,
                    ASK_CHANNEL_DESCRIPTION,
                    Json(tags),
                    Json(settings),
                ),
            )
            if _is_oracle_backend():
                # Oracle MERGE has no reliable RETURNING here -- fetch the id
                # with a follow-up SELECT instead (see the .sql file's note).
                cur.execute(
                    load("ask_thread_select_channel_id"),
                    (shay_workspace_id, ASK_CHANNEL_NAME),
                )
            row = cur.fetchone()
        if row is None:
            raise ValueError("Unable to create Aryx Ask channel for Shay workspace")
        return str(row[0])

    def ensure_thread_and_user_message(
        self,
        *,
        workspace_id: int,
        shay_workspace_id: str,
        thread_id: str,
        request_id: str,
        question: str,
    ) -> dict[str, Any]:
        channel_id = self.ensure_channel(shay_workspace_id, workspace_id)
        self.validate_thread_id_available_or_owned(shay_workspace_id, thread_id)
        title = normalize_thread_title(question)
        metadata = {
            "source": "aryx_ask",
            "workspace_id": int(workspace_id),
            "request_status": REQUEST_STATUS_IN_PROGRESS,
        }
        oracle = _is_oracle_backend()
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                load("ask_thread_ensure_thread"),
                (thread_id, title, "Aryx Ask thread", channel_id),
            )
            if oracle:
                # Oracle MERGE has no reliable RETURNING here -- see the
                # .sql file's note; fetch the row with a follow-up SELECT.
                cur.execute(load("ask_thread_select_thread_row"), (thread_id,))
            thread_row = cur.fetchone()
            insert_params = message_insert_params(
                thread_id=thread_id,
                message_id=str(uuid.uuid4()),
                content=question,
                message_type="user",
                request_id=request_id,
                is_ai_processed=False,
                ai_provider=None,
                ai_model=None,
                ai_processing_time=None,
                metadata=metadata,
                citations=[],
                usage={},
            )
            if oracle:
                message_row = _insert_message_oracle(cur, insert_params)
            else:
                cur.execute(load("ask_thread_insert_message"), insert_params)
                message_row = cur.fetchone()
            request_claimed = message_row is not None
            if message_row is None:
                cur.execute(
                    load("ask_thread_select_request_message"),
                    (thread_id, request_id),
                )
                message_row = cur.fetchone()
            if message_row is None:
                raise ValueError("Unable to claim or load the Ask request")
            # Oracle's override has 2 correlated subqueries + the final WHERE
            # (3 occurrences); Postgres's UPDATE...FROM only needs 2 -- oracledb
            # binds positionally by occurrence order, not by :N label (verified
            # live), so this needs its own count per backend.
            touch_thread_params = (thread_id,) * 3 if oracle else (thread_id, thread_id)
            cur.execute(load("ask_thread_touch_thread"), touch_thread_params)
            cur.execute(load("ask_thread_touch_channel"), (channel_id, channel_id, channel_id))
        existing_question = str(message_row[3])
        if not request_claimed and existing_question != question:
            raise ValueError("Ask request id is already used for a different question")
        return {
            "thread_id": str(thread_row[0]),
            "channel_id": channel_id,
            "created_thread": True,
            "user_message_id": str(message_row[0]),
            "user_sequence_number": int(message_row[1]),
            "request_claimed": request_claimed,
        }

    def append_assistant_message(
        self,
        *,
        thread_id: str,
        channel_id: str,
        request_id: str,
        answer: str,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        usage = result.get("usage") or {}
        metadata = {
            "source": "aryx_ask",
            "terms": result.get("terms") or [],
            "tools_called": result.get("tools_called") or [],
            "grounding": result.get("grounding"),
            "session_data": result.get("session_data") or {},
            "cpq_payload": result.get("cpq_payload"),
            "json_response": result.get("json_response"),
            "json_button_flag": result.get("json_button_flag", False),
            "beautify": result.get("beautify", ""),
            "beautify_button_flag": result.get("beautify_button_flag", False),
            "api_share_button_flag": result.get("api_share_button_flag", False),
            "error": result.get("error"),
        }
        grounding = result.get("grounding") or {}
        citations = normalize_grounding_citations(grounding)
        insert_params = message_insert_params(
            thread_id=thread_id,
            message_id=str(uuid.uuid4()),
            content=answer,
            message_type="system",
            request_id=request_id,
            is_ai_processed=True,
            ai_provider="aryx",
            ai_model=usage.get("answer_model"),
            ai_processing_time=usage.get("latency_ms"),
            metadata=metadata,
            citations=citations,
            usage=usage,
        )
        oracle = _is_oracle_backend()
        with self._pool.connection() as conn, conn.cursor() as cur:
            if oracle:
                row = _insert_message_oracle(cur, insert_params)
            else:
                cur.execute(load("ask_thread_insert_message"), insert_params)
                row = cur.fetchone()
            if row is None:
                raise ValueError("Unable to persist the Aryx Ask response")
            request_status = (
                REQUEST_STATUS_FAILED if result.get("error") else REQUEST_STATUS_COMPLETED
            )
            cur.execute(
                load("ask_thread_update_request_status"),
                (request_status, thread_id, request_id),
            )
            # See ensure_thread_and_user_message's note on why Oracle needs 3
            # occurrences here (2 correlated subqueries + WHERE) vs 2 for
            # Postgres's UPDATE...FROM.
            touch_thread_params = (thread_id,) * 3 if oracle else (thread_id, thread_id)
            cur.execute(load("ask_thread_touch_thread"), touch_thread_params)
            cur.execute(load("ask_thread_touch_channel"), (channel_id, channel_id, channel_id))
        return {
            "assistant_message_id": str(row[0]),
            "sequence_number": int(row[1]),
            "citations": citations,
        }

    def mark_request_retryable(self, thread_id: str, request_id: str) -> None:
        """Release a claimed request after failure-response persistence fails."""
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                load("ask_thread_update_request_status"),
                (REQUEST_STATUS_FAILED, thread_id, request_id),
            )

    def mark_request_completed(self, thread_id: str, request_id: str) -> None:
        """Prevent another LLM call after a successful Ask run."""
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                load("ask_thread_update_request_status"),
                (REQUEST_STATUS_COMPLETED, thread_id, request_id),
            )

    def get_completed_response(
        self,
        shay_workspace_id: str,
        thread_id: str,
        request_id: str,
    ) -> dict[str, Any] | None:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                load("ask_thread_select_cached_response"),
                (thread_id, request_id, shay_workspace_id, ASK_CHANNEL_NAME),
            )
            row = cur.fetchone()
        if row is None:
            return None
        metadata = _as_json(row[2]) or {}
        return {
            "answer": row[1],
            "terms": metadata.get("terms") or [],
            "tools_called": metadata.get("tools_called") or [],
            "usage": _as_json(row[4]) or {},
            "grounding": metadata.get("grounding"),
            "session_data": metadata.get("session_data") or {},
            "cpq_payload": metadata.get("cpq_payload"),
            "json_response": metadata.get("json_response"),
            "json_button_flag": metadata.get("json_button_flag", False),
            "beautify": metadata.get("beautify", ""),
            "beautify_button_flag": metadata.get("beautify_button_flag", False),
            "api_share_button_flag": metadata.get("api_share_button_flag", False),
            "error": metadata.get("error"),
            "citations": _as_json(row[3]) or [],
        }

    def conversation_history(
        self,
        thread_id: str,
        before_request_id: str,
        limit_pairs: int = 6,
    ) -> list[dict[str, str]]:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                load("ask_thread_select_history"),
                (thread_id, before_request_id, thread_id, max(int(limit_pairs), 1) * 2),
            )
            rows = cur.fetchall()
        return [
            {"role": "assistant" if row[0] == "system" else "user", "text": row[1]}
            for row in rows
        ]

    def list_threads(
        self,
        workspace_id: int,
        shay_workspace_id: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        self.validate_mapping(workspace_id, shay_workspace_id)
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                load("ask_thread_list_threads"),
                (shay_workspace_id, ASK_CHANNEL_NAME, int(limit)),
            )
            rows = cur.fetchall()
        return [
            {
                "id": row[0],
                "title": row[1],
                "message_count": row[2],
                "updated_at": row[3],
            }
            for row in rows
        ]

    def list_messages(
        self,
        workspace_id: int,
        shay_workspace_id: str,
        thread_id: str,
        before_sequence: int | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        self.validate_thread(workspace_id, shay_workspace_id, thread_id)
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                load("ask_thread_list_messages"),
                (thread_id, before_sequence, before_sequence, int(limit)),
            )
            rows = cur.fetchall()
        messages = []
        for row in rows:
            metadata = _as_json(row[6]) or {}
            usage = _as_json(row[8]) or {}
            messages.append({
                "id": row[0],
                "role": "assistant" if row[1] == "system" else "user",
                "content": row[2],
                "sequence_number": row[3],
                "request_id": row[4],
                "created_at": row[5],
                "citations": _as_json(row[7]) or [],
                "usage": usage,
                "json_response": metadata.get("json_response"),
                "json_button_flag": metadata.get("json_button_flag", False),
                "beautify": metadata.get("beautify", ""),
                "beautify_button_flag": metadata.get("beautify_button_flag", False),
                "api_share_button_flag": metadata.get("api_share_button_flag", False),
                "session_data": metadata.get("session_data") or {},
            })
        return messages


def get_ask_thread_store() -> AryxAskThreadStore:
    """Return an Ask thread store bound to the configured Aryx DSN.

    Works on both backends -- see docs/OCI_POSTGRES_PARITY_AUDIT.md for the
    Oracle port (MERGE-based upserts + a Python-side retry-safety path in
    _insert_message_oracle(), since Oracle has no `xmax` equivalent).
    """
    settings = get_settings()
    return AryxAskThreadStore(settings.effective_dsn())
