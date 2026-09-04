"""
Shared helpers for the channels route package.

Split out of the original app/routes/channels.py (2,630 lines) as part of
the Raven style-compliance file-splitting pass (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5). These two
functions are used by more than one submodule (validate_uuid everywhere;
get_channel_admins by the member-management submodules), so they live here
rather than being duplicated.
"""

import uuid
from typing import List

from fastapi import HTTPException, status
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.channel_member import ChannelMember


def validate_uuid(uuid_string: str, field_name: str = "ID") -> uuid.UUID:
    """Validate and return UUID from string, or raise HTTPException if invalid"""
    try:
        return uuid.UUID(uuid_string)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid {field_name} format. Must be a valid UUID."
        )


async def get_channel_admins(channel_id: uuid.UUID, db: AsyncSession) -> List[User]:
    """
    Get all admin users for a channel

    Args:
        channel_id: Channel UUID
        db: Database session

    Returns:
        List[User]: List of admin users for the channel
    """
    # Find all channel members with admin role
    admin_members_stmt = select(ChannelMember).where(
        and_(
            ChannelMember.channel_id == channel_id,
            ChannelMember.role.ilike("admin"),  # Case-insensitive match
            ChannelMember.is_active == True
        )
    )
    admin_members_result = await db.execute(admin_members_stmt)
    admin_members = admin_members_result.scalars().all()

    # Get user objects for admin members
    admin_user_ids = [member.user_id for member in admin_members]

    if not admin_user_ids:
        return []

    users_stmt = select(User).where(
        and_(
            User.id.in_(admin_user_ids),
            User.is_active == True
        )
    )
    users_result = await db.execute(users_stmt)
    admin_users = users_result.scalars().all()

    return list(admin_users)
