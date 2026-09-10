"""
create_message sub-step: build the MessageResponse for a newly created
message (author lookup + attachment details).

Split out of app/routes/messages/messages_create.py — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, wave B2.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.attachment import Attachment
from app.models.message import Message, Thread
from app.schemas.message import MessageResponse, UserBean, Citation, AttachmentDetails


async def _load_user_bean(db: AsyncSession, message: Message):
    if not message.user_id:
        return None

    user_stmt = select(User).where(User.id == message.user_id)
    user_result = await db.execute(user_stmt)
    user_obj = user_result.scalar_one_or_none()
    if not user_obj:
        return None

    return UserBean(
        id=str(user_obj.id),
        email=user_obj.email_id,
        name=user_obj.name,
        role=user_obj.role,
        avatar_url=user_obj.avatar_url
    )


async def _load_attachment_details(db: AsyncSession, message: Message, attachment_ids):
    if not attachment_ids:
        return []

    attachment_stmt = select(Attachment).where(Attachment.message_id == message.id)
    attachment_result = await db.execute(attachment_stmt)
    attachments = attachment_result.scalars().all()

    return [
        AttachmentDetails(
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
        )
        for attachment in attachments
    ]


async def build_create_message_response(
    db: AsyncSession,
    message: Message,
    thread: Thread,
    attachment_ids,
) -> MessageResponse:
    """Assemble the MessageResponse payload for a newly created message."""
    user_details = await _load_user_bean(db, message)
    attachment_details = await _load_attachment_details(db, message, attachment_ids)

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
