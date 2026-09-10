"""
Channel/thread ID parsing + access-check guard clauses for GET / (list
datasources).

Private module: split out of list_datasources.py (Raven style-compliance,
wave B4) — validating channel_id/thread_id format and the caller's access
to them is independent of the query-building and pagination that follow.
"""

import uuid
from typing import Optional, Tuple

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.utils.channel_access import check_channel_access, check_channel_access_by_thread


async def resolve_list_scope(
    db: AsyncSession,
    user,
    channel_id: Optional[str],
    thread_id: Optional[str],
) -> Tuple[Optional[uuid.UUID], Optional[uuid.UUID]]:
    """Validate channel_id/thread_id formats and the caller's access to them.

    Returns (channel_uuid, thread_uuid).
    """
    if channel_id:
        await check_channel_access(db, user, channel_id)

    channel_uuid = None
    if channel_id:
        try:
            channel_uuid = uuid.UUID(channel_id) if isinstance(channel_id, str) else channel_id
        except (ValueError, AttributeError):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid channel_id format: {channel_id}"
            )

    thread_uuid = None
    if thread_id:
        try:
            thread_uuid = uuid.UUID(thread_id)
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid thread_id format: {thread_id}"
            )
        await check_channel_access_by_thread(db, user, thread_id)

    return channel_uuid, thread_uuid
