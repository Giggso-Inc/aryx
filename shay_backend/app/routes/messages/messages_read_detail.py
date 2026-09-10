"""
GET /message/{message_id} — get_message_details.

Split out of app/routes/messages/messages_read.py — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, wave B2.
"""

from fastapi import APIRouter, HTTPException, status, Request, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.user import User
from app.models.channel import Channel
from app.models.message import Message, Thread
from app.models.attachment import Attachment
from app.schemas.message import MessageResponse, UserBean, Citation, AttachmentDetails

router = APIRouter()


@router.get("/message/{message_id}", response_model=MessageResponse)
async def get_message_details(
    message_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> MessageResponse:
    """Get message details by message ID"""
    user = await get_current_user_required(request)

    # Get message
    stmt = select(Message).where(Message.id == message_id)
    result = await db.execute(stmt)
    message = result.scalar_one_or_none()

    if not message:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message not found"
        )

    # Get thread
    stmt = select(Thread).where(Thread.id == message.thread_id)
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

    # Return message details in the same structure as MessageResponse (include citations and usage_metrics from DB)
    return MessageResponse(
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
