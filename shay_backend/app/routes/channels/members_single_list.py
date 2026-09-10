"""
GET /{channel_id}/members — list_channel_members.

Split out of members_single.py in wave B3 of the Raven style-compliance
line-count pass (see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md) to
bring members_single.py under 150 lines; originally split out of
app/routes/channels.py (2,630 lines) in Phase 5.
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, status, Request, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.channel import Channel
from app.models.channel_member import ChannelMember
from app.models.company import Company
from app.models.user import User
from app.utils.channel_access import check_channel_access
from app.schemas.channel_member import ChannelMemberUserList, ChannelMemberUserResponse
from .helpers import validate_uuid

router = APIRouter()


@router.get("/{channel_id}/members", response_model=ChannelMemberUserList)
async def list_channel_members(
    channel_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    include_inactive: bool = Query(False, description="Include inactive memberships"),
    search: Optional[str] = Query(None, description="Filter by user name or email contains"),
) -> ChannelMemberUserList:
    """
    List users who have access to a channel (members), with pagination and optional search.

    This endpoint provides a paginated list of channel members with user details. Admins can view
    regardless of company; non-admins must belong to the same company.

    Author: Pranhav Vimalbalaji
    Version: 1.0.0
    Last date modified: 13/08/2025
    """
    current_user = await get_current_user_required(request)

    # Check channel access - user must be super admin or channel member
    await check_channel_access(db, current_user, channel_id)

    # Validate channel_id as UUID
    channel_uuid = validate_uuid(channel_id, "channel ID")

    # Ensure channel exists
    stmt = select(Channel).where(Channel.id == channel_uuid)
    result = await db.execute(stmt)
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found")

    filters = [ChannelMember.channel_id == channel.id]
    if not include_inactive:
        filters.append(ChannelMember.is_active == True)

    # Join to users and company (left join since company_id might be null)
    base_query = (
        select(ChannelMember, User, Company)
        .join(User, User.id == ChannelMember.user_id)
        .outerjoin(Company, Company.id == User.company_id)
        .where(*filters)
        .order_by(User.name.nullslast(), User.email_id.nullslast())
    )

    if search:
        like = f"%{search}%"
        base_query = base_query.where(
            (User.name.ilike(like)) | (User.email_id.ilike(like))
        )

    # Pagination
    offset = (page - 1) * size
    items_query = base_query.offset(offset).limit(size)
    items_res = await db.execute(items_query)
    rows = items_res.all()

    # Count
    count_query = (
        select(func.count(ChannelMember.id))
        .join(User, User.id == ChannelMember.user_id)
        .where(*filters)
    )
    if search:
        like = f"%{search}%"
        count_query = count_query.where((User.name.ilike(like)) | (User.email_id.ilike(like)))
    total = (await db.execute(count_query)).scalar()

    items = [
        ChannelMemberUserResponse(
            user_id=str(user.id),
            email_id=user.email_id,
            name=user.name,
            avatar_url=user.avatar_url,
            user_role=user.role,
            membership_role=member.role,
            company_id=str(company.id) if company else None,
            company_name=company.name if company else None,
        )
        for member, user, company in rows
    ]

    return ChannelMemberUserList(items=items, total=total)
