"""PUT /{channel_id}/members/{user_id}  update_channel_member

Split from the original members.py (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Wave B4).
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.member import GGMember
from app.schemas.gg_channels import GGChannelMemberResponse, GGChannelMemberUpdate

from .helpers import _member_resp, _to_uuid

router = APIRouter()


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
