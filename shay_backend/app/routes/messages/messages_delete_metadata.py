"""
delete_message sub-step: recompute thread/channel message counts and
last_message_at after a message (and its dependents) are removed.

Split out of app/routes/messages/messages_delete.py — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, wave B2.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.channel import Channel
from app.models.message import Message, Thread


async def recompute_deletion_metadata(
    db: AsyncSession,
    thread: Thread,
    channel: Channel,
    thread_uuid: UUID,
    total_deleted: int,
) -> None:
    """Decrement thread/channel message counts and refresh last_message_at."""
    # Thread message count
    if thread.message_count >= total_deleted:
        thread.message_count -= total_deleted
    else:
        thread.message_count = 0

    last_message_query = select(Message).where(
        Message.thread_id == thread_uuid
    ).order_by(Message.sequence_number.desc()).limit(1)
    last_message_result = await db.execute(last_message_query)
    last_message = last_message_result.scalar_one_or_none()
    thread.last_message_at = last_message.created_at if last_message else None

    # Channel message count
    if channel.message_count >= total_deleted:
        channel.message_count -= total_deleted
    else:
        channel.message_count = 0

    channel_last_message_query = select(Message).where(Message.thread_id.in_(
        select(Thread.id).where(Thread.channel_id == channel.id)
    )).order_by(Message.created_at.desc()).limit(1)
    channel_last_message_result = await db.execute(channel_last_message_query)
    channel_last_message = channel_last_message_result.scalar_one_or_none()
    channel.last_message_at = channel_last_message.created_at if channel_last_message else None
