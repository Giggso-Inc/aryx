"""
delete_thread sub-steps: thread/channel lookup and permission checks.

Split out of app/routes/messages/threads_delete.py — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, wave B2.
"""

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.channel import Channel
from app.models.message import Thread
from app.models.user import User


async def get_thread_or_404(db: AsyncSession, thread_id: str) -> Thread:
    """Fetch the thread being deleted, or raise 404."""
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


def check_delete_thread_permissions(channel: Channel, user: User) -> None:
    """Raise 403 unless the user can access the channel and is an admin."""
    if not channel.is_accessible_by_user(user.company_id, user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to channel"
        )

    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can delete threads"
        )
