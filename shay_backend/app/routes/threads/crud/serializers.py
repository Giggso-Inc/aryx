"""
Shared response-shaping helper for the thread CRUD endpoints.

Split from app/routes/threads/crud.py (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).
"""

from typing import Optional

from app.models.message import Thread
from app.schemas.message import ThreadResponse


def thread_to_response(thread: Thread, first_message_id: Optional[str] = None) -> ThreadResponse:
    return ThreadResponse(
        id=str(thread.id),
        title=thread.title,
        description=thread.description,
        channel_id=str(thread.channel_id),
        is_active=thread.is_active,
        is_archived=thread.is_archived,
        message_count=thread.message_count,
        last_message_at=thread.last_message_at,
        ai_enabled=thread.ai_enabled,
        ai_summary=thread.ai_summary,
        first_message_id=first_message_id,
        created_at=thread.created_at,
        updated_at=thread.updated_at,
    )
