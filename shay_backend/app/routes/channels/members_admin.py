"""
PUT and DELETE /{channel_id}/members/{user_id} — admin-only membership role
update and removal.

Split out of the original app/routes/channels.py (2,630 lines) — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5.
"""

from datetime import datetime

from fastapi import APIRouter, HTTPException, status, Request, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.channel import Channel
from app.models.channel_member import ChannelMember
from app.services.audit_service import log as audit_log_write
from app.schemas.channel_member import (
    ChannelMemberResponse,
    ChannelMemberUpdate,
    ChannelMemberUpdateResponse,
)
from .helpers import validate_uuid

router = APIRouter()


@router.put("/{channel_id}/members/{update_user_id}", response_model=ChannelMemberUpdateResponse)
async def update_channel_member(
    channel_id: str,
    update_user_id: str,
    update_data: ChannelMemberUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ChannelMemberUpdateResponse:
    """Update a channel member's role/permissions. Admins only."""
    current_user = await get_current_user_required(request)

    # Only admins can update member roles
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can update member roles"
        )

    # Validate channel_id as UUID
    channel_uuid = validate_uuid(channel_id, "channel ID")

    # Check if channel exists
    stmt = select(Channel).where(Channel.id == channel_uuid)
    result = await db.execute(stmt)
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found")

    # Validate update_user_id as UUID
    update_user_uuid = validate_uuid(update_user_id, "user ID")

    # Check if membership exists
    member_stmt = select(ChannelMember).where(
        ChannelMember.channel_id == channel.id,
        ChannelMember.user_id == update_user_uuid,
    )
    member_result = await db.execute(member_stmt)
    member = member_result.scalar_one_or_none()
    if not member:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User is not a member of this channel"
        )

    # Update member role and permissions
    member.role = update_data.role
    if update_data.permissions is not None:
        member.permissions = update_data.permissions
    member.updated_at = datetime.utcnow()
    await audit_log_write(db, current_user.id, "channel.member_updated", "channel", channel_uuid, channel_id=channel_uuid, details={"member_id": str(update_user_uuid)})
    await db.commit()
    await db.refresh(member)

    updated_member = ChannelMemberResponse(
        id=str(member.id),
        channel_id=str(member.channel_id),
        user_id=str(member.user_id),
        role=member.role,
        is_active=member.is_active,
    )

    return ChannelMemberUpdateResponse(
        message="Member role updated successfully",
        updated_member=updated_member
    )


@router.delete("/{channel_id}/members/{delete_user_id}")
async def remove_channel_member(
    channel_id: str,
    delete_user_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Remove a user's channel membership. Admins only."""
    current_user = await get_current_user_required(request)

    # Only admins can remove members
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can remove channel members"
        )

    # Validate channel_id as UUID
    channel_uuid = validate_uuid(channel_id, "channel ID")

    # Check if channel exists
    stmt = select(Channel).where(Channel.id == channel_uuid)
    result = await db.execute(stmt)
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found")

    # Validate delete_user_id as UUID
    delete_user_uuid = validate_uuid(delete_user_id, "user ID")

    # Check if membership exists
    member_stmt = select(ChannelMember).where(
        ChannelMember.channel_id == channel.id,
        ChannelMember.user_id == delete_user_uuid,
    )
    member_result = await db.execute(member_stmt)
    member = member_result.scalar_one_or_none()
    if not member:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User is not a member of this channel"
        )

    await audit_log_write(db, current_user.id, "channel.member_removed", "channel", channel_uuid, channel_id=channel_uuid, details={"member_id": str(delete_user_uuid)})
    await db.delete(member)
    await db.commit()

    return {"message": "Member removed from channel successfully"}
