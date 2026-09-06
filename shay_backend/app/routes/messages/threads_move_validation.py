"""
move_thread sub-steps: load/validate the thread and the two channels
involved in a move, and check permissions.

Split out of app/routes/messages/threads_move.py — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, wave B2.
"""

from typing import Tuple

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.channel import Channel
from app.models.message import Thread
from app.models.user import User


def _is_message_channel(ch: Channel) -> bool:
    """Regular channel = "message" type (DB may store as string or integer 1)."""
    if ch.channel_type is None:
        return False
    s = str(ch.channel_type).lower()
    return s == "message" or (isinstance(ch.channel_type, int) and ch.channel_type == 1)


async def load_thread_for_move(db: AsyncSession, thread_id, new_channel_id) -> Thread:
    """Fetch the thread being moved and confirm it isn't already in new_channel_id."""
    stmt = select(Thread).where(Thread.id == thread_id)
    result = await db.execute(stmt)
    thread = result.scalar_one_or_none()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    if thread.channel_id == new_channel_id:
        raise HTTPException(status_code=400, detail="Thread is already in this channel")
    return thread


async def load_and_validate_move_channels(
    db: AsyncSession, old_channel_id, new_channel_id
) -> Tuple[Channel, Channel]:
    """Fetch both channels and confirm they're both regular, same-workspace channels."""
    stmt_src = select(Channel).where(Channel.id == old_channel_id)
    result_src = await db.execute(stmt_src)
    source_channel = result_src.scalar_one_or_none()

    stmt_dest = select(Channel).where(Channel.id == new_channel_id)
    result_dest = await db.execute(stmt_dest)
    dest_channel = result_dest.scalar_one_or_none()

    if not source_channel or not dest_channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    if not _is_message_channel(source_channel) or not _is_message_channel(dest_channel):
        raise HTTPException(
            status_code=400,
            detail="Thread moves are only allowed between regular (message-type) channels",
        )

    if source_channel.workspace_id != dest_channel.workspace_id:
        raise HTTPException(status_code=400, detail="Cannot move thread across workspaces")

    return source_channel, dest_channel


def check_move_permission(source_channel: Channel, user: User) -> None:
    """Raise 403 if the caller doesn't have access to the source channel."""
    if not source_channel.is_accessible_by_user(str(user.company_id), user.role or ""):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to source channel",
        )


def check_thread_movable(thread: Thread) -> None:
    """Raise 400 unless the thread is active and not archived."""
    if not thread.is_active or thread.is_archived:
        raise HTTPException(
            status_code=400,
            detail="Only active, non-archived threads can be moved",
        )
