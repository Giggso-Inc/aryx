"""
GET /threads — list_threads.

Split out of the original app/routes/messages.py (2,513 lines) — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5.

Registration order note: GET /threads (list_threads, a literal path) must
be registered before any GET /{thread_id}-style dynamic route elsewhere in
this package (messages_read_thread.get_thread_messages), or the literal
string "threads" would be swallowed by the dynamic pattern. See
app/routes/messages/__init__.py.

Wave B2: get_thread_details (GET /threads/{thread_id}) split out to its own
sibling file, threads_detail.py.
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, status, Request, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.channel import Channel
from app.models.message import Thread
from app.schemas.message import ThreadResponse, ThreadList
from .threads_first_message import get_first_message_id
from .threads_list_sort import apply_thread_sort

router = APIRouter()


@router.get("/threads", response_model=ThreadList)
async def list_threads(
    channel_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    search: Optional[str] = Query(None),
    is_archived: Optional[bool] = Query(False, description="Filter by archived status. True for archived threads, False for active threads"),
    sort_by: Optional[str] = Query("last_message_at", description="Sort by: created_at, updated_at, last_message_at, message_count"),
    sort_order: Optional[str] = Query("desc", description="Sort order: asc (ascending) or desc (descending)")
) -> ThreadList:
    """List threads in a channel

    Query Parameters:
    - channel_id: Required - ID of the channel
    - page: Page number (default: 1)
    - size: Page size (default: 10, max: 100)
    - search: Search by thread title
    - is_archived: Filter by archived status (default: false for active threads)
    - sort_by: last_message_at (default), created_at, updated_at, message_count
    - sort_order: asc (ascending) or desc (descending, default)
    """
    user = await get_current_user_required(request)

    # Get channel
    stmt = select(Channel).where(Channel.id == channel_id)
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

    # Build query
    query = select(Thread).where(Thread.channel_id == channel_id)

    # Add archived status filter
    query = query.where(Thread.is_archived == is_archived)

    # Add search filter
    if search:
        query = query.where(Thread.title.ilike(f"%{search}%"))

    # Add sorting
    query = apply_thread_sort(query, sort_by, sort_order)

    # Add pagination
    offset = (page - 1) * size
    query = query.offset(offset).limit(size)

    # Execute query
    result = await db.execute(query)
    threads = result.scalars().all()

    # Get total count
    count_query = select(func.count(Thread.id)).where(Thread.channel_id == channel_id)

    # Add archived status filter to count query
    count_query = count_query.where(Thread.is_archived == is_archived)

    if search:
        count_query = count_query.where(Thread.title.ilike(f"%{search}%"))

    count_result = await db.execute(count_query)
    total = count_result.scalar()

    # Get first message ID for each thread
    thread_responses = []
    for thread in threads:
        first_message_id = await get_first_message_id(db, thread.id)

        thread_response = ThreadResponse(
            id=str(thread.id),
            title=thread.title,
            description=thread.description,
            channel_id=str(thread.channel_id),
            is_active=thread.is_active,
            is_archived=thread.is_archived,
            message_count=thread.message_count,
            last_message_at=thread.last_message_at,
            ai_enabled=thread.ai_enabled,
            ai_summary=thread.ai_summary,
            first_message_id=first_message_id,
            created_at=thread.created_at,
            updated_at=thread.updated_at
        )
        thread_responses.append(thread_response)

    return ThreadList(
        threads=thread_responses,
        total=total,
        page=page,
        size=size
    )
