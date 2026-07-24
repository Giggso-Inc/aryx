"""Shared request-state and SQL parameter contracts for Aryx Ask threads."""

from __future__ import annotations

from typing import Any

from psycopg.types.json import Json

REQUEST_STATUS_IN_PROGRESS = "in_progress"
REQUEST_STATUS_FAILED = "failed"
REQUEST_STATUS_COMPLETED = "completed"


def message_insert_params(
    *,
    thread_id: str,
    message_id: str,
    content: str,
    message_type: str,
    request_id: str,
    is_ai_processed: bool,
    ai_provider: str | None,
    ai_model: str | None,
    ai_processing_time: int | None,
    metadata: dict[str, Any],
    citations: list[dict[str, Any]],
    usage: dict[str, Any],
) -> tuple[Any, ...]:
    """Build params in ask_thread_insert_message.sql placeholder order."""
    return (
        thread_id,
        message_id,
        content,
        message_type,
        thread_id,
        request_id,
        is_ai_processed,
        ai_provider,
        ai_model,
        ai_processing_time,
        Json(metadata),
        Json(citations),
        Json(usage),
    )
