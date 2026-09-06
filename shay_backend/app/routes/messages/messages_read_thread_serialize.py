"""
get_thread_messages sub-steps: batch-load users/attachments for a page of
messages and assemble the MessageList response.

Split out of app/routes/messages/messages_read_thread.py — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, wave B2.
"""

from typing import Dict, List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.message import Message, Thread
from app.models.attachment import Attachment
from app.schemas.message import MessageResponse, MessageList, UserBean, Citation, AttachmentDetails


async def load_users_for_messages(db: AsyncSession, messages: List[Message]) -> Dict[str, User]:
    """Batch-load the distinct users referenced by a page of messages."""
    user_ids = [m.user_id for m in messages if m.user_id]
    if not user_ids:
        return {}

    user_stmt = select(User).where(User.id.in_(user_ids))
    user_result = await db.execute(user_stmt)
    user_list = user_result.scalars().all()
    return {str(u.id): u for u in user_list}


async def load_attachments_for_messages(db: AsyncSession, messages: List[Message]) -> Dict[str, List[AttachmentDetails]]:
    """Batch-load attachment details, grouped by message id."""
    message_ids = [str(m.id) for m in messages]
    attachments_by_message: Dict[str, List[AttachmentDetails]] = {}
    if not message_ids:
        return attachments_by_message

    attachment_stmt = select(Attachment).where(Attachment.message_id.in_(message_ids))
    attachment_result = await db.execute(attachment_stmt)
    attachments = attachment_result.scalars().all()

    for attachment in attachments:
        message_id = str(attachment.message_id)
        attachments_by_message.setdefault(message_id, []).append(AttachmentDetails(
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
    return attachments_by_message


def build_message_list_response(
    messages: List[Message],
    thread: Thread,
    users: Dict[str, User],
    attachments_by_message: Dict[str, List[AttachmentDetails]],
    total: int,
    page: int,
    size: int,
) -> MessageList:
    """Assemble the MessageList response for a page of thread messages."""
    return MessageList(
        messages=[
            MessageResponse(
                id=str(m.id),
                content=m.content,
                message_type=m.message_type,
                thread_id=str(m.thread_id),
                channel_id=str(thread.channel_id),
                user_id=str(m.user_id) if m.user_id else None,
                query_id=str(m.query_id) if m.query_id else None,
                userBean=UserBean(
                    id=str(m.user_id),
                    email=users.get(str(m.user_id)).email_id if m.user_id and users.get(str(m.user_id)) else None,
                    name=users.get(str(m.user_id)).name if m.user_id and users.get(str(m.user_id)) else None,
                    role=users.get(str(m.user_id)).role if m.user_id and users.get(str(m.user_id)) else None,
                    avatar_url=users.get(str(m.user_id)).avatar_url if m.user_id and users.get(str(m.user_id)) else None
                ) if m.user_id and users.get(str(m.user_id)) else None,
                is_ai_processed=m.is_ai_processed,
                ai_provider=m.ai_provider,
                ai_model=m.ai_model,
                ai_processing_time=m.ai_processing_time,
                is_visible=m.is_visible,
                is_pinned=m.is_pinned,
                sequence_number=m.sequence_number,
                attachment_ids=[str(aid) for aid in m.attachment_ids] if m.attachment_ids else None,
                attachments=attachments_by_message.get(str(m.id), None),
                citations=[Citation(name=c["name"], type=c["type"]) for c in m.citations] if m.citations else None,
                usage_metrics=m.usage_metrics,
                created_at=m.created_at,
                updated_at=m.updated_at
            ) for m in messages
        ],
        total=total,
        page=page,
        size=size
    )
