"""
Thread-level member management (mounted at /api/v1/threads):
  GET/POST     /{thread_id}/members
  PUT/DELETE   /{thread_id}/members/{user_id}
"""

from datetime import datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.member import GGMember
from app.schemas.member import MemberCreate, MemberUpdate, MemberResponse, MemberList

router = APIRouter()


def _member_to_response(m: GGMember) -> MemberResponse:
    return MemberResponse(
        id=str(m.id),
        user_id=str(m.user_id),
        level=m.level,
        workspace_id=str(m.workspace_id) if m.workspace_id else None,
        channel_id=str(m.channel_id)     if m.channel_id   else None,
        thread_id=str(m.thread_id)       if m.thread_id    else None,
        role=m.role,
        is_active=m.is_active,
        permissions=m.permissions,
        invited_by=str(m.invited_by) if m.invited_by else None,
        joined_at=m.joined_at,
        created_at=m.created_at,
        updated_at=m.updated_at,
    )


@router.get("/{thread_id}/members", response_model=MemberList)
async def list_thread_members(
    thread_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
) -> MemberList:
    """List thread-level member overrides (level='thread' only)."""
    await get_current_user_required(request, db)

    try:
        t_uuid = UUID(thread_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid thread_id format")

    offset = (page - 1) * size
    stmt = (
        select(GGMember)
        .where(and_(GGMember.thread_id == t_uuid, GGMember.level == "thread"))
        .offset(offset)
        .limit(size)
    )
    result = await db.execute(stmt)
    members = result.scalars().all()

    count_stmt = select(func.count(GGMember.id)).where(
        and_(GGMember.thread_id == t_uuid, GGMember.level == "thread")
    )
    total = (await db.execute(count_stmt)).scalar()

    return MemberList(
        members=[_member_to_response(m) for m in members],
        total=total,
        page=page,
        size=size,
    )


@router.post("/{thread_id}/members", response_model=MemberResponse, status_code=201)
async def add_thread_member(
    thread_id: str,
    member_data: MemberCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> MemberResponse:
    """Add (or override) a user's role at thread level."""
    await get_current_user_required(request, db)

    try:
        t_uuid = UUID(thread_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid thread_id format")

    if member_data.level != "thread" or str(member_data.thread_id) != thread_id:
        raise HTTPException(
            status_code=422,
            detail="level must be 'thread' and thread_id in body must match the URL param",
        )

    member = GGMember(
        id=uuid4(),
        user_id=member_data.user_id,
        thread_id=t_uuid,
        level="thread",
        role=member_data.role,
        permissions=member_data.permissions or {},
        invited_by=member_data.invited_by,
        joined_at=datetime.utcnow(),
    )
    db.add(member)
    try:
        await db.commit()
        await db.refresh(member)
    except Exception as exc:
        await db.rollback()
        if "unique" in str(exc).lower():
            raise HTTPException(status_code=409, detail="User already has a thread-level membership.")
        raise

    return _member_to_response(member)


@router.put("/{thread_id}/members/{user_id}", response_model=MemberResponse)
async def update_thread_member(
    thread_id: str,
    user_id: str,
    member_data: MemberUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> MemberResponse:
    """Update a thread-level member override."""
    await get_current_user_required(request, db)

    try:
        t_uuid = UUID(thread_id)
        u_uuid = UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID format")

    stmt = select(GGMember).where(and_(
        GGMember.thread_id == t_uuid,
        GGMember.user_id == u_uuid,
        GGMember.level == "thread",
    ))
    result = await db.execute(stmt)
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=404, detail="Thread membership not found")

    for field, value in member_data.model_dump(exclude_unset=True).items():
        setattr(member, field, value)

    await db.commit()
    await db.refresh(member)
    return _member_to_response(member)


@router.delete("/{thread_id}/members/{user_id}")
async def remove_thread_member(
    thread_id: str,
    user_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Remove a thread-level membership override."""
    await get_current_user_required(request, db)

    try:
        t_uuid = UUID(thread_id)
        u_uuid = UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID format")

    stmt = select(GGMember).where(and_(
        GGMember.thread_id == t_uuid,
        GGMember.user_id == u_uuid,
        GGMember.level == "thread",
    ))
    result = await db.execute(stmt)
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=404, detail="Thread membership not found")

    await db.delete(member)
    await db.commit()
    return {"message": "Thread membership removed successfully"}
