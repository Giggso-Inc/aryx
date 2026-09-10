"""
Shared helper: look up a thread's first message id (lowest sequence_number),
used by both list_threads and get_thread_details.

Split out of app/routes/messages/threads_list.py — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, wave B2.
"""

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.message import Message


async def get_first_message_id(db: AsyncSession, thread_id) -> Optional[str]:
    """Return the id (as str) of the lowest-sequence_number message in a thread, or None."""
    first_message_query = select(Message.id).where(
        Message.thread_id == thread_id
    ).order_by(Message.sequence_number.asc()).limit(1)

    first_message_result = await db.execute(first_message_query)
    first_message = first_message_result.scalar_one_or_none()
    return str(first_message) if first_message else None
