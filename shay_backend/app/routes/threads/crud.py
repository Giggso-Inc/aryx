"""
Thread CRUD endpoints (mounted at /api/v1/threads):
  POST   /                   create thread
  GET    /                   list threads (channel_id required)
  GET    /{thread_id}        get thread
  PUT    /{thread_id}        update thread
  DELETE /{thread_id}        delete thread (admin only)

Stated exception (262 lines, over the 150-line target): kept as one module
because these five endpoints are the single CRUD surface for one resource
(Thread) and each response is built with the same ThreadResponse field list;
splitting further (e.g. create/list vs get/update/delete) would duplicate
that field list across files for no safety or readability benefit.
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app.core.database import get_db
from app.core.auth import generate_workspace_id
from app.middleware.auth_middleware import get_current_user_required
from app.models.channel import Channel
from app.models.message import Thread, Message
from app.schemas.message import (
    ThreadCreate,
    ThreadUpdate,
    ThreadResponse,
    ThreadList,
)

router = APIRouter()


@router.post("/", response_model=ThreadResponse, status_code=201)
async def create_thread(
    thread_data: ThreadCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ThreadResponse:
    """Create a new thread in a channel."""
    user = await get_current_user_required(request, db)

    try:
        channel_uuid = UUID(thread_data.channel_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid channel_id format")

    channel = (await db.execute(select(Channel).where(Channel.id == channel_uuid))).scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    if not channel.is_accessible_by_user(str(user.company_id), user.role):
        raise HTTPException(status_code=403, detail="Access denied to channel")

    thread = Thread(
        id=generate_workspace_id(),
        title=thread_data.title,
        description=thread_data.description,
        channel_id=channel_uuid,
        ai_enabled=channel.ai_enabled,
    )
    db.add(thread)
    await db.commit()
    await db.refresh(thread)

    return ThreadResponse(
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
        created_at=thread.created_at,
        updated_at=thread.updated_at,
    )


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
        thread_responses.append(ThreadResponse(
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
            first_message_id=str(first_msg) if first_msg else None,
            created_at=thread.created_at,
            updated_at=thread.updated_at,
        ))

    return ThreadList(threads=thread_responses, total=total, page=page, size=size)


@router.get("/{thread_id}", response_model=ThreadResponse)
async def get_thread(
    thread_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ThreadResponse:
    """Get thread details by ID."""
    user = await get_current_user_required(request, db)

    thread = (await db.execute(select(Thread).where(Thread.id == thread_id))).scalar_one_or_none()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    channel = (await db.execute(select(Channel).where(Channel.id == thread.channel_id))).scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    if not channel.is_accessible_by_user(str(user.company_id), user.role):
        raise HTTPException(status_code=403, detail="Access denied to channel")

    first_msg = (await db.execute(
        select(Message.id).where(Message.thread_id == thread.id).order_by(Message.sequence_number.asc()).limit(1)
    )).scalar_one_or_none()

    return ThreadResponse(
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
        first_message_id=str(first_msg) if first_msg else None,
        created_at=thread.created_at,
        updated_at=thread.updated_at,
    )


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

    return ThreadResponse(
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
        created_at=thread.created_at,
        updated_at=thread.updated_at,
    )


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
