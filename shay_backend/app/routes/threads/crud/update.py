"""
PUT /{thread_id} (update_thread) — mounted at /api/v1/threads.

Split from app/routes/threads/crud.py (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.channel import Channel
from app.models.message import Thread
from app.schemas.message import ThreadUpdate, ThreadResponse

from .serializers import thread_to_response

router = APIRouter()


@router.put("/{thread_id}", response_model=ThreadResponse)
async def update_thread(
    thread_id: str,
    thread_update: ThreadUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ThreadResponse:
    """Update a thread's title, description, status, or AI settings."""
    user = await get_current_user_required(request, db)

    thread = (await db.execute(select(Thread).where(Thread.id == thread_id))).scalar_one_or_none()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    channel = (await db.execute(select(Channel).where(Channel.id == thread.channel_id))).scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    if not channel.is_accessible_by_user(str(user.company_id), user.role):
        raise HTTPException(status_code=403, detail="Access denied to channel")

    for field, value in thread_update.model_dump(exclude_unset=True).items():
        setattr(thread, field, value)
    thread.updated_at = datetime.utcnow()

    await db.commit()
    await db.refresh(thread)

    return thread_to_response(thread)
