"""
delete_message sub-steps: id parsing, message/thread/channel lookup, and
permission checks.

Split out of app/routes/messages/messages_delete.py — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, wave B2.
"""

from typing import Tuple
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.channel import Channel
from app.models.message import Message, Thread


def parse_delete_ids(message_id: str, thread_id: str) -> Tuple[UUID, UUID]:
    """Parse message_id/thread_id strings into UUIDs, or raise 400."""
    try:
        return UUID(message_id), UUID(thread_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid message_id or thread_id format"
        )


async def get_message_for_delete(db: AsyncSession, message_uuid: UUID, thread_uuid: UUID) -> Message:
    """Fetch the message being deleted and confirm it belongs to thread_uuid."""
    stmt = select(Message).where(Message.id == message_uuid)
    result = await db.execute(stmt)
    message = result.scalar_one_or_none()

    if not message:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message not found"
        )

    if message.thread_id != thread_uuid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Message does not belong to the specified thread"
        )

    return message


async def get_thread_or_404(db: AsyncSession, thread_uuid: UUID) -> Thread:
    """Fetch the thread the message belongs to, or raise 404."""
    stmt = select(Thread).where(Thread.id == thread_uuid)
    result = await db.execute(stmt)
    thread = result.scalar_one_or_none()

    if not thread:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Thread not found"
        )
    return thread


async def get_channel_or_404(db: AsyncSession, channel_id) -> Channel:
    """Fetch the channel the thread belongs to, or raise 404."""
    stmt = select(Channel).where(Channel.id == channel_id)
    result = await db.execute(stmt)
    channel = result.scalar_one_or_none()

    if not channel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Channel not found"
        )
    return channel


def check_delete_permissions(channel: Channel, message: Message, user: User) -> None:
    """Raise 403 if the user can't access the channel or delete this message."""
    if not channel.is_accessible_by_user(user.company_id, user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to channel"
        )

    # Only the creator or an admin can delete
    if message.user_id != user.id and user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only delete your own messages"
        )
