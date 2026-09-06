"""
DELETE /delete — delete_message.

Split out of the original app/routes/messages.py (2,513 lines) — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5.

Wave B2 follow-up: the Phase-5 file kept this endpoint as one long function
under a "stated exception" (shared, partially-mutated thread/channel/message
state across dependent-message cleanup, attachment/S3 unlinking, and
metadata recomputation). Re-examined: each concern only needs specific
ids/counts as explicit inputs and returns explicit outputs — no opaque
half-mutated blob has to cross a module boundary. The steps now live in:
  - messages_delete_lookup: id parsing, message/thread/channel fetch, perms
  - messages_delete_dependents: query_id-referencing message cleanup
  - messages_delete_attachments: main message's storage/attachment cleanup
  - messages_delete_ai_responses: AIResponse row cleanup for the message
  - messages_delete_metadata: thread/channel count + last_message_at recompute
  - messages_delete_persist: audit log + delete the message row
"""

from fastapi import APIRouter, Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.schemas.message import MessageDelete
from .socket_events import emit_message_created_event
from .messages_delete_lookup import (
    parse_delete_ids,
    get_message_for_delete,
    get_thread_or_404,
    get_channel_or_404,
    check_delete_permissions,
)
from .messages_delete_dependents import cleanup_dependent_messages
from .messages_delete_attachments import delete_and_unlink_message_attachments
from .messages_delete_ai_responses import delete_ai_responses_for_message
from .messages_delete_metadata import recompute_deletion_metadata
from .messages_delete_persist import audit_and_delete_message

router = APIRouter()


@router.delete("/delete", response_model=dict)
async def delete_message(
    message_delete: MessageDelete,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> dict:
    """
    Delete an existing message (internal comment).

    This endpoint deletes a message and handles cleanup:
    - Unlinks attachments from the message
    - Deletes associated AI responses
    - Updates thread and channel message counts

    Author: System
    Version: 1.0.0
    """
    user = await get_current_user_required(request)

    message_uuid, thread_uuid = parse_delete_ids(message_delete.message_id, message_delete.thread_id)
    message = await get_message_for_delete(db, message_uuid, thread_uuid)
    thread = await get_thread_or_404(db, thread_uuid)
    channel = await get_channel_or_404(db, thread.channel_id)
    check_delete_permissions(channel, message, user)

    dependent_messages, dep_attachments_deleted, dep_ai_deleted = await cleanup_dependent_messages(db, message)
    main_attachments_deleted = await delete_and_unlink_message_attachments(db, message)
    deleted_attachments_count = dep_attachments_deleted + main_attachments_deleted

    ai_responses = await delete_ai_responses_for_message(db, message)

    await audit_and_delete_message(db, message, user.id)

    total_deleted = 1 + len(dependent_messages)
    await recompute_deletion_metadata(db, thread, channel, thread_uuid, total_deleted)

    # Store IDs before deletion for socket event
    channel_id_str = str(thread.channel_id)
    thread_id_str = str(message.thread_id)
    message_id_str = str(message.id)

    await db.commit()

    # Emit socket event for message deletion
    await emit_message_created_event(
        channel_id=channel_id_str,
        thread_id=thread_id_str,
        message_id=message_id_str
    )

    return {
        "message": "Message deleted successfully",
        "message_id": message_delete.message_id,
        "thread_id": message_delete.thread_id,
        "deleted_attachments": deleted_attachments_count,
        "deleted_ai_responses": len(ai_responses) + dep_ai_deleted,
        "deleted_query_id_messages": len(dependent_messages),
    }
