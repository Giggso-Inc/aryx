"""
GET /{thread_id} — get_thread_messages.

Split out of app/routes/messages/messages_read.py — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, wave B2.

Registration order note: this is a single-segment dynamic path and MUST be
registered after threads_list's GET /threads (also a single-segment path,
but literal) — see app/routes/messages/__init__.py.
"""

from fastapi import APIRouter, HTTPException, status, Request, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.channel import Channel
from app.models.message import Message, Thread
from app.schemas.message import MessageList
from .messages_read_thread_serialize import (
    load_users_for_messages,
    load_attachments_for_messages,
    build_message_list_response,
)

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

    users = await load_users_for_messages(db, messages)
    attachments_by_message = await load_attachments_for_messages(db, messages)

    return build_message_list_response(
        messages, thread, users, attachments_by_message, total, page, size
    )
