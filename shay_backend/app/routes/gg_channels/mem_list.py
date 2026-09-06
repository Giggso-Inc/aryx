"""GET /{channel_id}/members  list_channel_members

Split from the original members.py (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Wave B4).
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.member import GGMember
from app.schemas.gg_channels import GGChannelMemberList

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
