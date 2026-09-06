"""
create_message sub-steps: thread/channel lookup, access check, sequencing.

Split out of app/routes/messages/messages_create.py — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, wave B2.
"""

from fastapi import HTTPException, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.channel import Channel
from app.models.message import Message, Thread


async def get_thread_or_404(db: AsyncSession, thread_id) -> Thread:
    """Fetch the thread a message is being created in, or raise 404."""
    stmt = select(Thread).where(Thread.id == thread_id)
    result = await db.execute(stmt)
    thread = result.scalar_one_or_none()

    if not thread:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Thread not found"
        )
    return thread


async def get_channel_or_404(db: AsyncSession, channel_id) -> Channel:
    """Fetch the channel a thread belongs to, or raise 404."""
    stmt = select(Channel).where(Channel.id == channel_id)
    result = await db.execute(stmt)
    channel = result.scalar_one_or_none()

    if not channel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Channel not found"
        )
    return channel


def check_channel_access(channel: Channel, user: User) -> None:
    """Raise 403 if the user cannot post into this channel."""
    if not channel.is_accessible_by_user(user.company_id, user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to channel"
        )


async def get_next_sequence_number(db: AsyncSession, thread_id) -> int:
    """Compute the next message sequence number within a thread."""
    seq_query = select(func.max(Message.sequence_number)).where(Message.thread_id == thread_id)
    seq_result = await db.execute(seq_query)
    max_seq = seq_result.scalar() or 0
    return max_seq + 1
