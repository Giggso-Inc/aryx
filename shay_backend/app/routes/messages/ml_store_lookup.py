"""
store_ml_messages sub-steps: thread_id parsing and thread/channel lookup.

Split out of app/routes/messages/ml_store.py — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, wave B2.
"""

from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.channel import Channel
from app.models.message import Thread


def parse_thread_uuid(thread_id: str) -> Optional[UUID]:
    """Parse a thread_id string into a UUID, or None if malformed."""
    try:
        return UUID(thread_id)
    except ValueError:
        return None


async def get_thread(db: AsyncSession, thread_uuid: UUID) -> Optional[Thread]:
    """Fetch a thread by id, or None if it doesn't exist."""
    stmt = select(Thread).where(Thread.id == thread_uuid)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_channel(db: AsyncSession, channel_id) -> Optional[Channel]:
    """Fetch a channel by id, or None if it doesn't exist."""
    stmt = select(Channel).where(Channel.id == channel_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()
