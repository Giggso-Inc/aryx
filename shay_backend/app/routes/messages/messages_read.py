"""
GET /{thread_id} and GET /message/{message_id} — message read endpoints.

Split out of the original app/routes/messages.py (2,513 lines) — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5.

Registration order note: GET /{thread_id} here is a single-segment dynamic
path and MUST be registered after threads_list's GET /threads (also a
single-segment path, but literal) — see app/routes/messages/__init__.py.
"""

from fastapi import APIRouter, HTTPException, status, Request, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.user import User
from app.models.channel import Channel
from app.models.message import Message, Thread
from app.models.attachment import Attachment
from app.schemas.message import MessageResponse, MessageList, UserBean, Citation, AttachmentDetails

router = APIRouter()


@router.get("/{thread_id}", response_model=MessageList)
async def get_thread_messages(
    thread_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=100)
) -> MessageList:
    """Get messages in a thread"""
    user = await get_current_user_required(request)

    # Get thread
    stmt = select(Thread).where(Thread.id == thread_id)
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

    # Get messages
    query = select(Message).where(Message.thread_id == thread_id)
    offset = (page - 1) * size
    query = query.offset(offset).limit(size).order_by(Message.sequence_number)

    result = await db.execute(query)
    messages = result.scalars().all()

    # Get total count
    count_query = select(func.count(Message.id)).where(Message.thread_id == thread_id)
    count_result = await db.execute(count_query)
    total = count_result.scalar()

    # Get user details for all messages
    user_ids = [m.user_id for m in messages if m.user_id]
    users = {}
    if user_ids:
        user_stmt = select(User).where(User.id.in_(user_ids))
        user_result = await db.execute(user_stmt)
        user_list = user_result.scalars().all()
        users = {str(u.id): u for u in user_list}

    # Get attachment details for all messages
    message_ids = [str(m.id) for m in messages]
    attachments_by_message = {}
    if message_ids:
        from app.models.attachment import Attachment
        from app.schemas.message import AttachmentDetails

        attachment_stmt = select(Attachment).where(Attachment.message_id.in_(message_ids))
        attachment_result = await db.execute(attachment_stmt)
        attachments = attachment_result.scalars().all()

        for attachment in attachments:
            message_id = str(attachment.message_id)
            if message_id not in attachments_by_message:
                attachments_by_message[message_id] = []

            attachments_by_message[message_id].append(AttachmentDetails(
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
        from app.models.attachment import Attachment
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
