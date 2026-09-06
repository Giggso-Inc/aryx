"""
POST /update — update_message.

Split out of the original app/routes/messages.py (2,513 lines) — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5.

Wave B2 follow-up: the Phase-5 file kept this endpoint as one long function
under a "stated exception" (shared ORM state between attachment-diffing
and response-building). Re-examined: the attachment reconciliation only
needs the message/thread/channel ids and the new attachment_ids list as
explicit inputs, and the response builder already exists as a reusable
helper (messages_create_response.build_create_message_response) that just
needs the final message.attachment_ids — no opaque shared state actually
crosses a module boundary. The steps now live in:
  - messages_update_lookup: id parsing, message/thread/channel fetch, perms
  - messages_update_attachments: attachment_ids reconciliation
  - messages_update_persist: audit log, commit, refresh
  - messages_create_response (reused): response payload assembly
"""

from fastapi import APIRouter, Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.schemas.message import MessageUpdate, MessageResponse
from .socket_events import emit_message_created_event
from .messages_update_lookup import (
    parse_update_ids,
    get_message_for_update,
    get_thread_or_404,
    get_channel_or_404,
    check_update_permissions,
)
from .messages_update_attachments import reconcile_message_attachments
from .messages_update_persist import persist_updated_message
from .messages_create_response import build_create_message_response

router = APIRouter()


@router.post("/update", response_model=MessageResponse)
async def update_message(
    message_update: MessageUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> MessageResponse:
    """
    Update an existing message (internal comment).

    This endpoint allows updating message content, message type, and attachments.
    It handles both scenarios: with attachments and without attachments.

    Author: System
    Version: 1.0.0
    """
    user = await get_current_user_required(request)

    message_uuid, thread_uuid = parse_update_ids(message_update.message_id, message_update.thread_id)
    message = await get_message_for_update(db, message_uuid, thread_uuid)
    thread = await get_thread_or_404(db, thread_uuid)
    channel = await get_channel_or_404(db, thread.channel_id)
    check_update_permissions(channel, message, user)

    # Update message content and type
    message.content = message_update.content
    message.message_type = message_update.message_type

    # Update optional fields if provided
    if message_update.is_visible is not None:
        message.is_visible = message_update.is_visible
    if message_update.is_pinned is not None:
        message.is_pinned = message_update.is_pinned

    await reconcile_message_attachments(
        db, message, thread.channel_id, user.id, message_update.attachment_ids
    )

    await persist_updated_message(db, message, user.id)

    response = await build_create_message_response(db, message, thread, message.attachment_ids)

    # Emit socket event for message update
    await emit_message_created_event(
        channel_id=str(thread.channel_id),
        thread_id=str(message.thread_id),
        message_id=str(message.id)
    )

    return response
