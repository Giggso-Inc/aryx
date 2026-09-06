"""
GET / (list_threads) — mounted at /api/v1/threads.

Split from app/routes/threads/crud.py (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.channel import Channel
from app.models.message import Thread, Message
from app.schemas.message import ThreadList

from .serializers import thread_to_response

router = APIRouter()


@router.get("/", response_model=ThreadList)
async def list_threads(
    channel_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    search: Optional[str] = Query(None, description="Search by thread title"),
    is_archived: Optional[bool] = Query(False, description="Filter by archived status"),
    sort_by: Optional[str] = Query("last_message_at", description="Sort by: created_at, updated_at, last_message_at, message_count"),
    sort_order: Optional[str] = Query("desc", description="Sort order: asc or desc"),
) -> ThreadList:
    """List threads in a channel."""
    user = await get_current_user_required(request, db)

    channel = (await db.execute(select(Channel).where(Channel.id == channel_id))).scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    if not channel.is_accessible_by_user(str(user.company_id), user.role):
        raise HTTPException(status_code=403, detail="Access denied to channel")

    query = select(Thread).where(Thread.channel_id == channel_id, Thread.is_archived == is_archived)
    if search:
        query = query.where(Thread.title.ilike(f"%{search}%"))

    sort_col = {
        "created_at": Thread.created_at,
        "updated_at": Thread.updated_at,
        "message_count": Thread.message_count,
    }.get(sort_by)
    if sort_col is not None:
        query = query.order_by(sort_col.asc() if sort_order == "asc" else sort_col.desc())
    else:
        coalesced = func.coalesce(Thread.last_message_at, Thread.created_at)
        query = query.order_by(coalesced.asc() if sort_order == "asc" else coalesced.desc())

    count_query = select(func.count(Thread.id)).where(Thread.channel_id == channel_id, Thread.is_archived == is_archived)
    if search:
        count_query = count_query.where(Thread.title.ilike(f"%{search}%"))
    total = (await db.execute(count_query)).scalar()

    threads = (await db.execute(query.offset((page - 1) * size).limit(size))).scalars().all()

    thread_responses = []
    for thread in threads:
        first_msg = (await db.execute(
            select(Message.id).where(Message.thread_id == thread.id).order_by(Message.sequence_number.asc()).limit(1)
        )).scalar_one_or_none()
        thread_responses.append(
            thread_to_response(thread, first_message_id=str(first_msg) if first_msg else None)
        )

    return ThreadList(threads=thread_responses, total=total, page=page, size=size)
