"""Persistence for Aryx Ask conversations stored as Shay threads/messages."""

from __future__ import annotations

import re
import uuid
from typing import Any

from psycopg.types.json import Json

from aryx.config import get_settings
from aryx.queries import load
from aryx.store.pool import get_pool

ASK_CHANNEL_NAME = "__aryx_ask__"
ASK_CHANNEL_DESCRIPTION = "Hidden Aryx Ask conversation channel"


def _as_int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


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
        if row[1] == shay_workspace_id and row[2] == ASK_CHANNEL_NAME and row[3] is True:
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
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                load("ask_thread_ensure_thread"),
                (thread_id, title, "Aryx Ask thread", channel_id),
            )
            thread_row = cur.fetchone()
            cur.execute(
                load("ask_thread_insert_message"),
                (
                    thread_id,
                    thread_id,
                    str(uuid.uuid4()),
                    question,
                    "user",
                    thread_id,
                    request_id,
                    False,
                    None,
                    None,
                    None,
                    Json({"source": "aryx_ask", "workspace_id": int(workspace_id)}),
                    Json([]),
                    Json({}),
                ),
            )
            message_row = cur.fetchone()
            cur.execute(load("ask_thread_touch_thread"), (thread_id, thread_id))
            cur.execute(load("ask_thread_touch_channel"), (channel_id, channel_id, channel_id))
        request_claimed = bool(message_row[2])
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
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                load("ask_thread_insert_message"),
                (
                    thread_id,
                    thread_id,
                    str(uuid.uuid4()),
                    answer,
                    "system",
                    thread_id,
                    request_id,
                    True,
                    "aryx",
                    usage.get("answer_model"),
                    usage.get("latency_ms"),
                    Json(metadata),
                    Json(citations),
                    Json(usage),
                ),
            )
            row = cur.fetchone()
            cur.execute(load("ask_thread_touch_thread"), (thread_id, thread_id))
            cur.execute(load("ask_thread_touch_channel"), (channel_id, channel_id, channel_id))
        return {
            "assistant_message_id": str(row[0]),
            "sequence_number": int(row[1]),
            "citations": citations,
        }

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
        metadata = row[2] or {}
        return {
            "answer": row[1],
            "terms": metadata.get("terms") or [],
            "tools_called": metadata.get("tools_called") or [],
            "usage": row[4] or {},
            "grounding": metadata.get("grounding"),
            "session_data": metadata.get("session_data") or {},
            "cpq_payload": metadata.get("cpq_payload"),
            "json_response": metadata.get("json_response"),
            "json_button_flag": metadata.get("json_button_flag", False),
            "beautify": metadata.get("beautify", ""),
            "beautify_button_flag": metadata.get("beautify_button_flag", False),
            "api_share_button_flag": metadata.get("api_share_button_flag", False),
            "error": metadata.get("error"),
            "citations": row[3] or [],
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
            metadata = row[6] or {}
            usage = row[8] or {}
            messages.append({
                "id": row[0],
                "role": "assistant" if row[1] == "system" else "user",
                "content": row[2],
                "sequence_number": row[3],
                "request_id": row[4],
                "created_at": row[5],
                "citations": row[7] or [],
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
    """Return an Ask thread store bound to the configured Aryx DSN."""
    settings = get_settings()
    if settings.effective_db_backend() == "oci":
        raise RuntimeError(
            "Shay-backed Ask threads are not available with the OCI database backend"
        )
    return AryxAskThreadStore(settings.effective_dsn())
