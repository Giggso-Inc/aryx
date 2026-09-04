"""
POST / — create_message.

Split out of the original app/routes/messages.py (2,513 lines) — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5.

Stated exception: kept as one file rather than split further. A single
request here threads through thread/channel lookup, sequence-number
assignment, system-message query_id validation, attachment linking,
AI-processing scheduling, and mention-notification scheduling, all against
the same message/thread/channel objects being built up in one function —
splitting it would mean passing that half-built state across module
boundaries for no real readability gain.
"""

from datetime import datetime

from fastapi import APIRouter, HTTPException, status, Request, Depends, BackgroundTasks
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.auth import generate_message_id
from app.core.config import settings
from app.middleware.auth_middleware import get_current_user_required
from app.services.audit_service import log as audit_log_write
from app.services.link_shortener_service import link_shortener_service
from app.models.user import User
from app.models.channel import Channel
from app.models.message import Message, Thread
from app.models.attachment import Attachment
from app.schemas.message import MessageCreate, MessageResponse, UserBean, Citation, AttachmentDetails
from .socket_events import emit_message_created_event
from .system_user import get_or_create_system_user
from .mentions import process_mention_notifications
from .ai_processing import trigger_ai_processing

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

    # Get thread
    stmt = select(Thread).where(Thread.id == message_data.thread_id)
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

    # Get next sequence number
    seq_query = select(func.max(Message.sequence_number)).where(Message.thread_id == message_data.thread_id)
    seq_result = await db.execute(seq_query)
    max_seq = seq_result.scalar() or 0
    next_seq = max_seq + 1

    # Determine user_id and query_id based on message type
    user_id = user.id
    query_id = None

    if message_data.message_type == "system":
        # For system messages, use system user's ID and validate query_id
        system_user = await get_or_create_system_user(db)
        user_id = system_user.id

        if not message_data.query_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="query_id is required for system messages"
            )

        # Validate that the query message exists and is a user message
        query_stmt = select(Message).where(
            and_(
                Message.id == message_data.query_id,
                Message.thread_id == message_data.thread_id,
                Message.message_type == "user"
            )
        )
        query_result = await db.execute(query_stmt)
        query_message = query_result.scalar_one_or_none()

        if not query_message:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Query message not found or invalid"
            )

        query_id = message_data.query_id

    # Convert attachment_ids to UUIDs if provided
    attachment_uuids = None
    if message_data.attachment_ids:
        from uuid import UUID as UUIDType
        try:
            attachment_uuids = [UUIDType(attachment_id) for attachment_id in message_data.attachment_ids]
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid attachment ID format: {str(e)}"
            )

    # Create message
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

    # Handle attachments if provided
    if message_data.attachment_ids:
        from app.models.attachment import Attachment
        from uuid import UUID as UUIDType

        # Validate and link attachments
        for attachment_id in message_data.attachment_ids:
            try:
                attachment_uuid = UUIDType(attachment_id)
                attachment_stmt = select(Attachment).where(
                    and_(
                        Attachment.id == attachment_uuid,
                        Attachment.channel_id == thread.channel_id,
                        Attachment.user_id == user_id  # Ensure user owns the attachment
                    )
                )
                attachment_result = await db.execute(attachment_stmt)
                attachment = attachment_result.scalar_one_or_none()

                if attachment:
                    # Link attachment to message
                    attachment.message_id = message.id
                else:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"Attachment {attachment_id} not found or access denied"
                    )
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid attachment ID format: {attachment_id}"
                )

    # Update thread metadata
    thread.message_count += 1
    thread.last_message_at = datetime.utcnow()

    # Update channel metadata
    channel.message_count += 1
    channel.last_message_at = datetime.utcnow()
    await audit_log_write(db, user.id, "message.created", "message", message.id, channel_id=thread.channel_id, thread_id=message.thread_id, details={"message_type": message_data.message_type})
    await db.commit()
    await db.refresh(message)

    # Trigger AI processing if enabled
    if channel.ai_enabled and thread.ai_enabled and message_data.message_type == "user":
        background_tasks.add_task(trigger_ai_processing, message.id)

    # Process mention notifications for user messages only
    if message_data.message_type == "user" and message_data.content:
        # Use the canonical frontend root for real-time notifications.
        platform_url = settings.PLATFORM_URL

        # Construct redirect URL to view the thread (shortened; store thread_id/channel_id for move-safe links)
        redirect_url = await link_shortener_service.shorten(
            f"{platform_url}/threads/{channel.id}", db,
            thread_id=thread.id, channel_id=channel.id, entity_type="mention",
        ) if platform_url else "#"
        # Construct notification settings URL (shortened; channel-level)
        notification_settings_url = await link_shortener_service.shorten(
            f"{platform_url}/threads/{channel.id}?openSettings=true&tab=notification", db,
            channel_id=channel.id, entity_type="channel",
        ) if platform_url else "#"

        # Process mentions in background to avoid blocking the response
        background_tasks.add_task(
            process_mention_notifications,
            message_data.content,
            str(user.id),  # The user ID who posted the comment
            str(channel.id),  # The channel ID where the message was posted
            redirect_url,  # Pre-constructed redirect URL
            notification_settings_url  # Pre-constructed notification settings URL
        )

    # Get user details for the message
    user_details = None
    if message.user_id:
        user_stmt = select(User).where(User.id == message.user_id)
        user_result = await db.execute(user_stmt)
        user_obj = user_result.scalar_one_or_none()
        if user_obj:
            user_details = UserBean(
                id=str(user_obj.id),
                email=user_obj.email_id,
                name=user_obj.name,
                role=user_obj.role,
                avatar_url=user_obj.avatar_url
            )

    # Get attachment details for the message
    attachment_details = []
    if message_data.attachment_ids:
        from app.schemas.message import AttachmentDetails

        attachment_stmt = select(Attachment).where(Attachment.message_id == message.id)
        attachment_result = await db.execute(attachment_stmt)
        attachments = attachment_result.scalars().all()

        for attachment in attachments:
            attachment_details.append(AttachmentDetails(
                id=str(attachment.id),
                filename=attachment.filename,
                original_filename=attachment.original_filename,
                file_size=attachment.file_size,
                mime_type=attachment.mime_type,
                file_extension=attachment.file_extension,
                storage_url=attachment.storage_url,
                is_public=attachment.is_public,
                is_processed=attachment.is_processed,
                processing_status=attachment.processing_status,
                content_summary=attachment.content_summary,
                created_at=attachment.created_at
            ))

    # Prepare response data
    response = MessageResponse(
        id=str(message.id),
        content=message.content,
        message_type=message.message_type,
        thread_id=str(message.thread_id),
        channel_id=str(thread.channel_id),
        user_id=str(message.user_id) if message.user_id else None,
        query_id=str(message.query_id) if message.query_id else None,
        userBean=user_details,
        is_ai_processed=message.is_ai_processed,
        ai_provider=message.ai_provider,
        ai_model=message.ai_model,
        ai_processing_time=message.ai_processing_time,
        is_visible=message.is_visible,
        is_pinned=message.is_pinned,
        sequence_number=message.sequence_number,
        attachment_ids=[str(aid) for aid in message.attachment_ids] if message.attachment_ids else None,
        attachments=attachment_details if attachment_details else None,
        citations=[Citation(name=c["name"], type=c["type"]) for c in message.citations] if message.citations else None,
        usage_metrics=message.usage_metrics,
        created_at=message.created_at,
        updated_at=message.updated_at
    )

    # Emit socket event at the END - PURE EMISSION ONLY
    await emit_message_created_event(
        channel_id=str(thread.channel_id),
        thread_id=str(message.thread_id),
        message_id=str(message.id)
    )

    return response
