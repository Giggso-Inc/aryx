"""
POST /message/{message_id}/hide — soft-hide a message.

Split out of the original app/routes/messages.py (2,513 lines) — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5.
"""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, status, Request, Depends
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.services.audit_service import log as audit_log_write
from app.models.channel import Channel
from app.models.message import Message, Thread
from app.schemas.message import HideThreadMessagesResponse

router = APIRouter()


@router.post(
    "/message/{message_id}/hide",
    response_model=HideThreadMessagesResponse,
)
async def hide_thread_messages(
    message_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> HideThreadMessagesResponse:
    """
    Hide a message (soft-hide: sets is_visible=false). Channel and thread are derived from the message.
    When all messages in a thread are hidden, the thread can be hidden by the caller/other service.
    """
    user = await get_current_user_required(request)
    try:
        message_uuid = UUID(message_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid message_id format",
        )
    # Fetch message and derive channel via thread
    msg_stmt = select(Message).where(Message.id == message_uuid)
    msg_result = await db.execute(msg_stmt)
    message = msg_result.scalar_one_or_none()
    if not message:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message not found",
        )
    thread_stmt = select(Thread).where(Thread.id == message.thread_id)
    thread_result = await db.execute(thread_stmt)
    msg_thread = thread_result.scalar_one_or_none()
    channel_stmt = select(Channel).where(Channel.id == msg_thread.channel_id) if msg_thread else None
    if channel_stmt is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Thread not found",
        )
    channel_result = await db.execute(channel_stmt)
    channel = channel_result.scalar_one_or_none()
    if not channel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Channel not found",
        )
    if not channel.is_accessible_by_user(user.company_id, user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to channel",
        )
    now = datetime.utcnow()
    stmt = (
        update(Message)
        .where(Message.id == message_uuid)
        .values(is_visible=False, updated_at=now)
    )
    result = await db.execute(stmt)
    hidden_count = result.rowcount
    await audit_log_write(db, user.id, "message.hidden", "message", message_uuid, channel_id=message.channel_id, thread_id=message.thread_id)
    await db.commit()
    return HideThreadMessagesResponse(
        success=True,
        message="Message hidden",
        hidden_count=hidden_count,
        message_id=message_id,
    )
