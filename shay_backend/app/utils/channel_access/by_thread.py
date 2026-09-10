"""
Thread-to-channel access check — resolves a thread's channel_id then
delegates to check_channel_access.

Split out of app/utils/channel_access.py — see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md.
"""

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException, status

from app.models.user import User
from app.utils.channel_access.by_channel import check_channel_access


async def check_channel_access_by_thread(
    db: AsyncSession,
    user: User,
    thread_id: str,
    raise_on_denied: bool = True
) -> Optional[str]:
    """
    Check if a user has access to a channel via thread_id.

    This function gets the channel_id from the thread and then checks access.

    Args:
        db: Database session
        user: Current user object
        thread_id: Thread ID to get channel from (UUID string)
        raise_on_denied: If True, raises HTTPException on access denied. If False, returns None.

    Returns:
        Optional[str]: Channel ID if user has access, None otherwise (only if raise_on_denied=False)

    Raises:
        HTTPException: 404 if thread not found, 403 if access denied (if raise_on_denied=True)
    """
    import uuid
    from app.models.message import Thread

    # Validate thread_id format
    try:
        thread_uuid = uuid.UUID(thread_id)
    except ValueError:
        if raise_on_denied:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid thread ID format"
            )
        return None

    # Get thread to find channel_id
    thread_stmt = select(Thread).where(Thread.id == thread_uuid)
    thread_result = await db.execute(thread_stmt)
    thread = thread_result.scalar_one_or_none()

    if not thread:
        if raise_on_denied:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Thread not found"
            )
        return None

    # Check access to the channel
    has_access = await check_channel_access(
        db=db,
        user=user,
        channel_id=str(thread.channel_id),
        raise_on_denied=raise_on_denied
    )

    if has_access:
        return str(thread.channel_id)
    return None
