"""
Channel-level GGMember endpoints: list, add, update, remove.

Split from the original app/routes/gg_channels.py (Raven style-compliance
pass, see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2).
"""

from datetime import datetime
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.member import GGMember
from app.schemas.gg_channels import (
    GGChannelMemberCreate,
    GGChannelMemberList,
    GGChannelMemberResponse,
    GGChannelMemberUpdate,
)

from .helpers import _get_channel_or_404, _member_resp, _to_uuid

router = APIRouter()


@router.get("/{channel_id}/members", response_model=GGChannelMemberList)
async def list_channel_members(
    channel_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    role:      Optional[str]  = None,
    is_active: Optional[bool] = None,
) -> GGChannelMemberList:
    """List all GGMembers at channel scope (level='channel')."""
    await get_current_user_required(request, db)

    ch_uuid = _to_uuid(channel_id, "channel_id")
    await _get_channel_or_404(db, ch_uuid)

    filters = [
        GGMember.channel_id == ch_uuid,
        GGMember.level      == "channel",
    ]
    if role:
        filters.append(GGMember.role == role)
    if is_active is not None:
        filters.append(GGMember.is_active == is_active)

    base_q = select(GGMember).where(and_(*filters))
    total = (await db.execute(select(func.count()).select_from(base_q.subquery()))).scalar()
    members = (await db.execute(
        base_q.order_by(GGMember.created_at.desc()).offset((page - 1) * size).limit(size)
    )).scalars().all()

    return GGChannelMemberList(
        members=[_member_resp(m) for m in members],
        total=total,
        page=page,
        size=size,
        pages=(total + size - 1) // size,
    )


@router.post("/{channel_id}/members", response_model=GGChannelMemberResponse, status_code=201)
async def add_channel_member(
    channel_id: str,
    data: GGChannelMemberCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> GGChannelMemberResponse:
    """Add a user to a channel via GGMember (level='channel')."""
    user = await get_current_user_required(request, db)

    ch_uuid = _to_uuid(channel_id, "channel_id")
    ch = await _get_channel_or_404(db, ch_uuid)

    if not ch.is_accessible_by_user(user.company_id, user.role):
        raise HTTPException(status_code=403, detail="Access denied to this channel")

    member = GGMember(
        id=uuid4(),
        user_id=data.user_id,
        channel_id=ch_uuid,
        level="channel",
        role=data.role,
        permissions=data.permissions or {},
        invited_by=data.invited_by or user.id,
        joined_at=datetime.utcnow(),
    )
    db.add(member)
    try:
        await db.commit()
        await db.refresh(member)
    except Exception as exc:
        await db.rollback()
        if "unique" in str(exc).lower():
            raise HTTPException(status_code=409, detail="User already has a channel membership.")
        raise

    return _member_resp(member)


@router.put("/{channel_id}/members/{user_id}", response_model=GGChannelMemberResponse)
async def update_channel_member(
    channel_id: str,
    user_id:    str,
    data: GGChannelMemberUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> GGChannelMemberResponse:
    """Update a channel GGMember's role, permissions, or active status."""
    await get_current_user_required(request, db)

    ch_uuid   = _to_uuid(channel_id, "channel_id")
    user_uuid = _to_uuid(user_id,    "user_id")

    member = (await db.execute(
        select(GGMember).where(and_(
            GGMember.channel_id == ch_uuid,
            GGMember.user_id    == user_uuid,
            GGMember.level      == "channel",
        ))
    )).scalar_one_or_none()

    if not member:
        raise HTTPException(status_code=404, detail="Channel membership not found")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(member, field, value)

    await db.commit()
    await db.refresh(member)
    return _member_resp(member)


@router.delete("/{channel_id}/members/{user_id}", status_code=200)
async def remove_channel_member(
    channel_id: str,
    user_id:    str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Remove a GGMember from a channel."""
    await get_current_user_required(request, db)

    ch_uuid   = _to_uuid(channel_id, "channel_id")
    user_uuid = _to_uuid(user_id,    "user_id")

    member = (await db.execute(
        select(GGMember).where(and_(
            GGMember.channel_id == ch_uuid,
            GGMember.user_id    == user_uuid,
            GGMember.level      == "channel",
        ))
    )).scalar_one_or_none()

    if not member:
        raise HTTPException(status_code=404, detail="Channel membership not found")

    await db.delete(member)
    await db.commit()
    return {"message": "Channel member removed successfully"}
