"""
DELETE /{thread_id} (delete_thread) — mounted at /api/v1/threads.

Split from app/routes/threads/crud.py (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.channel import Channel
from app.models.message import Thread, Message

router = APIRouter()


@router.delete("/{thread_id}")
async def delete_thread(
    thread_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Delete a thread and all its messages (admin only)."""
    user = await get_current_user_required(request, db)

    thread = (await db.execute(select(Thread).where(Thread.id == thread_id))).scalar_one_or_none()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    channel = (await db.execute(select(Channel).where(Channel.id == thread.channel_id))).scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    if not channel.is_accessible_by_user(str(user.company_id), user.role):
        raise HTTPException(status_code=403, detail="Access denied to channel")
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Only administrators can delete threads")

    message_count = (await db.execute(
        select(func.count(Message.id)).where(Message.thread_id == thread_id)
    )).scalar()

    await db.delete(thread)
    await db.commit()

    return {
        "message": "Thread deleted successfully",
        "thread_id": thread_id,
        "messages_deleted": message_count,
    }
