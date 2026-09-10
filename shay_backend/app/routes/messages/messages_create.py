"""
POST / — create_message.

Split out of the original app/routes/messages.py (2,513 lines) — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5.

Wave B2 follow-up: the Phase-5 file kept this endpoint as one long function
under a "stated exception" (shared in-flight ORM state). Re-examined: each
step reads or writes explicit, narrow inputs (thread, channel, message,
ids) rather than an opaque shared blob, so the steps split cleanly into
named helpers in sibling modules:
  - messages_create_lookup: thread/channel fetch, access check, sequencing
  - messages_create_identity: user_id/query_id resolution
  - messages_create_attachments: attachment_ids parsing + linking
  - messages_create_persist: metadata bump, audit log, commit, refresh
  - messages_create_dispatch: background AI + mention-notification tasks
  - messages_create_response: response payload assembly
This file is now a thin orchestrator that calls those steps in sequence —
the only "stated exception" left is that the orchestration order itself
must stay in one place, which is what an orchestrator function is for.
"""

from fastapi import APIRouter, Request, Depends, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.auth import generate_message_id
from app.middleware.auth_middleware import get_current_user_required
from app.models.message import Message
from app.schemas.message import MessageCreate, MessageResponse
from .socket_events import emit_message_created_event
from .messages_create_lookup import (
    get_thread_or_404,
    get_channel_or_404,
    check_channel_access,
    get_next_sequence_number,
)
from .messages_create_identity import resolve_message_identity
from .messages_create_attachments import parse_attachment_uuids, link_attachments_to_message
from .messages_create_persist import persist_new_message
from .messages_create_dispatch import schedule_ai_processing, schedule_mention_notifications
from .messages_create_response import build_create_message_response

router = APIRouter()


@router.post("/", response_model=MessageResponse)
async def create_message(
    message_data: MessageCreate,
    background_tasks: BackgroundTasks,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> MessageResponse:
    """
    Create a new message and trigger AI processing.

    This endpoint creates a new message in a thread and can trigger AI processing based on
    the message type. It supports user messages, system messages, and AI responses.

    Author: Pranhav Vimalbalaji
    Version: 1.0.0
    Last date modified: 13/08/2025
    """
    user = await get_current_user_required(request)

    thread = await get_thread_or_404(db, message_data.thread_id)
    channel = await get_channel_or_404(db, thread.channel_id)
    check_channel_access(channel, user)

    next_seq = await get_next_sequence_number(db, message_data.thread_id)
    user_id, query_id = await resolve_message_identity(db, message_data, user)
    attachment_uuids = parse_attachment_uuids(message_data.attachment_ids)

    message = Message(
        id=generate_message_id(),
        content=message_data.content,
        message_type=message_data.message_type,
        thread_id=message_data.thread_id,
        user_id=user_id,
        query_id=query_id,
        sequence_number=next_seq,
        attachment_ids=attachment_uuids  # Store attachment_ids array in message
    )
    db.add(message)

    await link_attachments_to_message(
        db, message, message_data.attachment_ids, thread.channel_id, user_id
    )

    await persist_new_message(
        db, message, thread, channel, user.id, message_data.message_type
    )

    schedule_ai_processing(background_tasks, channel, thread, message, message_data)
    await schedule_mention_notifications(
        db, background_tasks, user.id, channel, thread, message_data
    )

    response = await build_create_message_response(
        db, message, thread, message_data.attachment_ids
    )

    # Emit socket event at the END - PURE EMISSION ONLY
    await emit_message_created_event(
        channel_id=str(thread.channel_id),
        thread_id=str(message.thread_id),
        message_id=str(message.id)
    )

    return response
