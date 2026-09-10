"""DELETE /{channel_id}/members/{user_id}  remove_channel_member

Split from the original members.py (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Wave B4).
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.member import GGMember

from .helpers import _to_uuid

router = APIRouter()


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
