"""
GET /{channel_id}/access — check_user_access.

Split out of detail.py in wave B3 of the Raven style-compliance line-count
pass (see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md) to bring detail.py
under 150 lines; originally split out of app/routes/channels.py (2,630
lines) in Phase 5.
"""

from fastapi import APIRouter, HTTPException, status, Request, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.channel import Channel
from app.models.channel_member import ChannelMember
from app.schemas.channel_member import ChannelAccessCheckResponse
from .helpers import validate_uuid

router = APIRouter()


@router.get("/{channel_id}/access", response_model=ChannelAccessCheckResponse)
async def check_user_access(
    channel_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ChannelAccessCheckResponse:
    """
    Check whether the current user has access to a channel.

    This endpoint verifies if the authenticated user (from JWT token) has access to the specified channel.
    Access is determined based on company membership, channel visibility, and explicit membership.

    Author: Pranhav Vimalbalaji
    Version: 1.0.0
    Last date modified: 13/08/2025
    """
    current_user = await get_current_user_required(request)

    # Validate channel_id as UUID
    channel_uuid = validate_uuid(channel_id, "channel ID")

    stmt = select(Channel).where(Channel.id == channel_uuid)
    result = await db.execute(stmt)
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found")

    # Use current user ID from JWT token
    target_user_id = str(current_user.id)

    # Company admin has unconditional access
    if current_user.is_admin:
        return ChannelAccessCheckResponse(has_access=True, reason="admin")

    # Non-admins must be in the same company as the channel
    if str(current_user.company_id) != str(channel.company_id):
        return ChannelAccessCheckResponse(has_access=False, reason="company_mismatch")

    # Public channel → access for company users
    if channel.is_public:
        return ChannelAccessCheckResponse(has_access=True, reason="public")

    # Membership check
    member_stmt = select(ChannelMember).where(
        ChannelMember.channel_id == channel.id,
        ChannelMember.user_id == target_user_id,
        ChannelMember.is_active == True,
    )
    member_result = await db.execute(member_stmt)
    membership = member_result.scalar_one_or_none()
    if membership:
        return ChannelAccessCheckResponse(has_access=True, reason="member")

    return ChannelAccessCheckResponse(has_access=False, reason="not_member")
