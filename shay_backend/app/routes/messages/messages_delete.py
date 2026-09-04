"""
DELETE /delete — delete_message.

Split out of the original app/routes/messages.py (2,513 lines) — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5.

Stated exception: kept as one file rather than split further. The
dependent-message cleanup (AI/system replies whose query_id points at this
message), attachment/S3 unlinking, and the thread/channel message-count and
last_message_at recomputation all read and mutate the same `thread`/
`channel`/`message` objects in one pass — splitting them would mean passing
that shared, partially-mutated state across module boundaries for no real
readability gain.
"""

from uuid import UUID

from fastapi import APIRouter, HTTPException, status, Request, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.services.audit_service import log as audit_log_write
from app.services.file_storage import get_file_storage_service
from app.models.channel import Channel
from app.models.message import Message, Thread
from app.models.ai_response import AIResponse
from app.schemas.message import MessageDelete
from .socket_events import emit_message_created_event

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

    # Validate message_id and thread_id
    try:
        message_uuid = UUID(message_delete.message_id)
        thread_uuid = UUID(message_delete.thread_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid message_id or thread_id format"
        )

    # Get message
    stmt = select(Message).where(Message.id == message_uuid)
    result = await db.execute(stmt)
    message = result.scalar_one_or_none()

    if not message:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message not found"
        )

    # Validate message belongs to the specified thread
    if message.thread_id != thread_uuid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Message does not belong to the specified thread"
        )

    # Get thread
    stmt = select(Thread).where(Thread.id == thread_uuid)
    result = await db.execute(stmt)
    thread = result.scalar_one_or_none()

    if not thread:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Thread not found"
        )

    # Get channel
    stmt = select(Channel).where(Channel.id == thread.channel_id)
    result = await db.execute(stmt)
    channel = result.scalar_one_or_none()

    if not channel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Channel not found"
        )

    # Check permissions
    if not channel.is_accessible_by_user(user.company_id, user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to channel"
        )

    # Check if user can delete this message (only the creator or admin can delete)
    if message.user_id != user.id and user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only delete your own messages"
        )

    from app.models.attachment import Attachment

    # Find and delete any messages that reference this message as query_id (e.g. AI responses in gg_messages)
    dependent_stmt = select(Message).where(Message.query_id == message.id)
    dependent_result = await db.execute(dependent_stmt)
    dependent_messages = dependent_result.scalars().all()

    deleted_attachments_count = 0
    deleted_dependent_ai_count = 0
    for dep_msg in dependent_messages:
        # Unlink attachments from dependent message
        if dep_msg.attachment_ids:
            dep_att_stmt = select(Attachment).where(Attachment.message_id == dep_msg.id)
            dep_att_result = await db.execute(dep_att_stmt)
            dep_attachments = dep_att_result.scalars().all()
            for att in dep_attachments:
                try:
                    storage_service = get_file_storage_service()
                    await storage_service.delete_file(att.file_path)
                    deleted_attachments_count += 1
                except Exception:
                    pass
                att.message_id = None
        # Delete AI responses for this dependent message
        dep_ai_stmt = select(AIResponse).where(AIResponse.message_id == dep_msg.id)
        dep_ai_result = await db.execute(dep_ai_stmt)
        dep_ai = dep_ai_result.scalars().all()
        for ai in dep_ai:
            await db.delete(ai)
            deleted_dependent_ai_count += 1
        await db.delete(dep_msg)

    # Delete attachments from S3 and unlink from the main message
    if message.attachment_ids:
        attachment_stmt = select(Attachment).where(Attachment.message_id == message.id)
        attachment_result = await db.execute(attachment_stmt)
        attachments = attachment_result.scalars().all()

        # Delete files from S3/storage
        storage_service = get_file_storage_service()
        for attachment in attachments:
            try:
                # Delete file from S3/storage
                print(f"Attempting to delete file from storage: {attachment.file_path}")
                print(f"Storage provider: {storage_service.provider.__class__.__name__}")
                result = await storage_service.delete_file(attachment.file_path)
                if result:
                    deleted_attachments_count += 1
                    print(f"Successfully deleted file: {attachment.file_path}")
                else:
                    print(f"Failed to delete file (returned False): {attachment.file_path}")
            except Exception as e:
                print(f"Failed to delete file {attachment.file_path} from storage: {e}")
                import traceback
                traceback.print_exc()
                # Continue with unlinking even if S3 deletion fails

            # Unlink attachment from message
            attachment.message_id = None

    # Delete AI responses associated with this message
    ai_responses_stmt = select(AIResponse).where(AIResponse.message_id == message.id)
    ai_responses_result = await db.execute(ai_responses_stmt)
    ai_responses = ai_responses_result.scalars().all()

    for ai_response in ai_responses:
        await db.delete(ai_response)

    await audit_log_write(db, user.id, "message.deleted", "message", message.id, channel_id=message.channel_id, thread_id=message.thread_id)
    # Delete the main message
    await db.delete(message)

    # Update thread metadata (decrease message count: main message + any dependent messages with query_id = this message)
    total_deleted = 1 + len(dependent_messages)
    if thread.message_count >= total_deleted:
        thread.message_count -= total_deleted
    else:
        thread.message_count = 0

    # Update last_message_at if this was the last message
    last_message_query = select(Message).where(Message.thread_id == thread_uuid).order_by(Message.sequence_number.desc()).limit(1)
    last_message_result = await db.execute(last_message_query)
    last_message = last_message_result.scalar_one_or_none()

    if last_message:
        thread.last_message_at = last_message.created_at
    else:
        thread.last_message_at = None

    # Update channel metadata (decrease message count by total deleted: main + dependents)
    if channel.message_count >= total_deleted:
        channel.message_count -= total_deleted
    else:
        channel.message_count = 0

    # Update channel last_message_at
    channel_last_message_query = select(Message).where(Message.thread_id.in_(
        select(Thread.id).where(Thread.channel_id == channel.id)
    )).order_by(Message.created_at.desc()).limit(1)
    channel_last_message_result = await db.execute(channel_last_message_query)
    channel_last_message = channel_last_message_result.scalar_one_or_none()

    if channel_last_message:
        channel.last_message_at = channel_last_message.created_at
    else:
        channel.last_message_at = None

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
        "deleted_ai_responses": len(ai_responses) + deleted_dependent_ai_count,
        "deleted_query_id_messages": len(dependent_messages),
    }
