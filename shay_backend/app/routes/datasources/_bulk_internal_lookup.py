"""
thread/channel/user resolution for the internal/bulk per-item loop.

Private module: used only by _bulk_internal_create_item.py.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.channel import Channel
from app.models.message import Thread

from ._bulk_internal_user_resolution import resolve_internal_bulk_user
from ._bulk_item_failure import BulkItemFailure


async def resolve_thread_channel_and_user(datasource_data, db: AsyncSession):
    """Resolve (thread, channel, user, thread_uuid) for an internal/bulk item.

    Raises BulkItemFailure for any of: invalid thread_id, thread not found,
    channel not found for thread, or no active user found for the company.
    """
    try:
        thread_uuid = uuid.UUID(datasource_data.thread_id)
    except (ValueError, TypeError):
        raise BulkItemFailure(datasource_data.name or "Unknown", f"Invalid thread_id format: {datasource_data.thread_id}")

    thread_stmt = select(Thread).where(Thread.id == thread_uuid)
    thread_result = await db.execute(thread_stmt)
    thread = thread_result.scalar_one_or_none()

    if not thread:
        raise BulkItemFailure(datasource_data.name or "Unknown", "Thread not found")

    channel_stmt = select(Channel).where(Channel.id == thread.channel_id)
    channel_result = await db.execute(channel_stmt)
    channel = channel_result.scalar_one_or_none()

    if not channel:
        raise BulkItemFailure(datasource_data.name or "Unknown", "Channel not found for thread")

    user = await resolve_internal_bulk_user(thread, channel, db)
    if not user:
        raise BulkItemFailure(datasource_data.name or "Unknown", "No active user found for channel's company")

    return thread, channel, user, thread_uuid
