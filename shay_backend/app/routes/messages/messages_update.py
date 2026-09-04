"""
POST /update — update_message.

Split out of the original app/routes/messages.py (2,513 lines) — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5.

Stated exception: kept as one file rather than split further. The
attachment-diffing logic (link new attachments, unlink ones no longer
referenced) operates on the same `message`/`thread`/`channel` objects as
the rest of the update and the response-building at the end re-reads that
same state — splitting it out would mean passing that half-updated ORM
state across module boundaries for no real readability gain.
"""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, status, Request, Depends
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.services.audit_service import log as audit_log_write
from app.models.user import User
from app.models.channel import Channel
from app.models.message import Message, Thread
from app.models.attachment import Attachment
from app.schemas.message import MessageUpdate, MessageResponse, UserBean, Citation, AttachmentDetails
from .socket_events import emit_message_created_event

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

    # Validate message_id and thread_id
    try:
        message_uuid = UUID(message_update.message_id)
        thread_uuid = UUID(message_update.thread_id)
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

    # Check if user can edit this message (only the creator or admin can edit)
    if message.user_id != user.id and user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only edit your own messages"
        )

    # Update message content and type
    message.content = message_update.content
    message.message_type = message_update.message_type

    # Update optional fields if provided
    if message_update.is_visible is not None:
        message.is_visible = message_update.is_visible
    if message_update.is_pinned is not None:
        message.is_pinned = message_update.is_pinned

    # Handle attachments
    from app.models.attachment import Attachment
    from uuid import UUID as UUIDType
    from app.schemas.message import AttachmentDetails

    # Get current attachments
    current_attachment_ids = set(message.attachment_ids) if message.attachment_ids else set()

    # Process new attachment_ids
    new_attachment_uuids = []
    if message_update.attachment_ids is not None:
        # Convert string IDs to UUIDs
        for attachment_id in message_update.attachment_ids:
            try:
                attachment_uuid = UUIDType(attachment_id)
                new_attachment_uuids.append(attachment_uuid)
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid attachment ID format: {attachment_id}"
                )

        # Validate and link new attachments
        new_attachment_ids_set = set(new_attachment_uuids)
        for attachment_uuid in new_attachment_uuids:
            attachment_stmt = select(Attachment).where(
                and_(
                    Attachment.id == attachment_uuid,
                    Attachment.channel_id == thread.channel_id,
                    Attachment.user_id == user.id  # Ensure user owns the attachment
                )
            )
            attachment_result = await db.execute(attachment_stmt)
            attachment = attachment_result.scalar_one_or_none()

            if not attachment:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Attachment {attachment_uuid} not found or access denied"
                )

            # Link attachment to message
            attachment.message_id = message.id

        # Unlink attachments that are no longer in the list
        attachments_to_unlink = current_attachment_ids - new_attachment_ids_set
        if attachments_to_unlink:
            unlink_stmt = select(Attachment).where(
                and_(
                    Attachment.id.in_(attachments_to_unlink),
                    Attachment.message_id == message.id
                )
            )
            unlink_result = await db.execute(unlink_stmt)
            attachments_to_remove = unlink_result.scalars().all()
            for attachment in attachments_to_remove:
                attachment.message_id = None

        # Update message.attachment_ids array
        # Empty list means remove all attachments, use None for empty array in database
        message.attachment_ids = new_attachment_uuids if new_attachment_uuids else None
    # If attachment_ids is None (not provided in request), don't change existing attachments

    # Update timestamp
    message.updated_at = datetime.utcnow()
    await audit_log_write(db, user.id, "message.updated", "message", message.id, channel_id=message.channel_id, thread_id=message.thread_id)
    await db.commit()
    await db.refresh(message)

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
    if message.attachment_ids:
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

    # Emit socket event for message update
    await emit_message_created_event(
        channel_id=str(thread.channel_id),
        thread_id=str(message.thread_id),
        message_id=str(message.id)
    )

    return response
