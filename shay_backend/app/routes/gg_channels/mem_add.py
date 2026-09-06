"""POST /{channel_id}/members  add_channel_member

Split from the original members.py (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Wave B4).
"""

from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.member import GGMember
from app.schemas.gg_channels import GGChannelMemberCreate, GGChannelMemberResponse

from .helpers import _get_channel_or_404, _member_resp, _to_uuid

router = APIRouter()


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
