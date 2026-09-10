"""
GET /threads/{thread_id}/summary and PUT /threads/{thread_id} — thread
summary and metadata update.

Split out of the original app/routes/messages.py (2,513 lines) — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5.
"""

from datetime import datetime

from fastapi import APIRouter, HTTPException, status, Request, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.services.audit_service import log as audit_log_write
from app.models.channel import Channel
from app.models.message import Thread
from app.schemas.message import ThreadSummary, ThreadUpdate, ThreadResponse

router = APIRouter()


@router.get("/threads/{thread_id}/summary", response_model=ThreadSummary)
async def get_thread_summary(
    thread_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> ThreadSummary:
    """Get thread summary"""
    user = await get_current_user_required(request)

    # Get thread
    stmt = select(Thread).where(Thread.id == thread_id)
    result = await db.execute(stmt)
    thread = result.scalar_one_or_none()

    if not thread:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Thread not found"
        )

    # Get channel
    stmt = select(Channel).where(Channel.id == thread.channel_id)
    result = await db.execute(stmt)
    channel = result.scalar_one_or_none()

    if not channel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Channel not found"
        )

    # Check permissions
    if not channel.is_accessible_by_user(user.company_id, user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to channel"
        )

    return ThreadSummary(
        thread_id=thread.id,
        title=thread.title,
        message_count=thread.message_count,
        last_message_at=thread.last_message_at,
        ai_summary=thread.ai_summary,
        created_at=thread.created_at
    )


@router.put("/threads/{thread_id}", response_model=ThreadResponse)
async def update_thread(
    thread_id: str,
    thread_update: ThreadUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> ThreadResponse:
    """Update a thread"""
    user = await get_current_user_required(request)

    # Get thread
    stmt = select(Thread).where(Thread.id == thread_id)
    result = await db.execute(stmt)
    thread = result.scalar_one_or_none()

    if not thread:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Thread not found"
        )

    # Get channel
    stmt = select(Channel).where(Channel.id == thread.channel_id)
    result = await db.execute(stmt)
    channel = result.scalar_one_or_none()

    if not channel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Channel not found"
        )

    # Check permissions
    if not channel.is_accessible_by_user(user.company_id, user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to channel"
        )

    # Update thread fields
    if thread_update.title is not None:
        thread.title = thread_update.title
    if thread_update.description is not None:
        thread.description = thread_update.description
    if thread_update.is_active is not None:
        thread.is_active = thread_update.is_active
    if thread_update.is_archived is not None:
        thread.is_archived = thread_update.is_archived
    if thread_update.ai_enabled is not None:
        thread.ai_enabled = thread_update.ai_enabled
    if thread_update.ai_summary is not None:
        thread.ai_summary = thread_update.ai_summary

    # Update timestamp
    thread.updated_at = datetime.utcnow()
    await audit_log_write(db, user.id, "thread.updated", "thread", thread.id, channel_id=thread.channel_id, thread_id=thread.id)
    await db.commit()
    await db.refresh(thread)

    return ThreadResponse.from_orm(thread)
