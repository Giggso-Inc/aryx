"""
Shared thread-lookup + channel-access helper for the three thread-scoped
task endpoints (thread_detail.py, thread_status.py, thread_create.py).

Split out of the former thread_tasks.py (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md): all three endpoints began
with the identical "load Thread, load its Channel, check
is_accessible_by_user" block, so it moved here rather than being copied
three times.
"""

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.user import User
from app.models.channel import Channel
from app.models.message import Message, Thread


async def load_thread_and_check_access(thread_id: str, user: User, db: AsyncSession) -> tuple[Thread, Channel]:
    """Load the thread and its channel, raising 404/403 as the original
    inline checks did. Returns (thread, channel)."""
    thread_stmt = select(Thread).where(Thread.id == thread_id)
    thread_result = await db.execute(thread_stmt)
    thread = thread_result.scalar_one_or_none()

    if not thread:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found")

    channel_stmt = select(Channel).where(Channel.id == thread.channel_id)
    channel_result = await db.execute(channel_stmt)
    channel = channel_result.scalar_one_or_none()

    if not channel or not channel.is_accessible_by_user(user.company_id, user.role):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to thread")

    return thread, channel


async def get_thread_message_ids(thread_id: str, db: AsyncSession) -> list:
    """Return the ids of every Message belonging to this thread."""
    thread_msg_ids_stmt = select(Message.id).where(Message.thread_id == thread_id)
    thread_msg_ids_result = await db.execute(thread_msg_ids_stmt)
    return [row[0] for row in thread_msg_ids_result.all()]
