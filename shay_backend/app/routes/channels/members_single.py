"""
POST /{channel_id}/members — add_channel_member: single-user membership
grant (upsert by email).

Split out of the original app/routes/channels.py (2,630 lines) — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5.

GET /{channel_id}/members (list_channel_members) was further split out to
members_single_list.py in wave B3 to bring this file under 150 lines.
"""

from fastapi import APIRouter, HTTPException, status, Request, Depends
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.auth import generate_channel_id
from app.middleware.auth_middleware import get_current_user_required
from app.models.user import User
from app.models.channel import Channel
from app.models.channel_member import ChannelMember
from app.services.audit_service import log as audit_log_write
from app.schemas.channel_member import SingleChannelMemberCreate, ChannelMemberResponse
from .helpers import validate_uuid
from .members_single_notify import notify_new_member

router = APIRouter()


# Primary endpoint: Single user addition by email (mail_id)
@router.post("/{channel_id}/members", response_model=ChannelMemberResponse)
async def add_channel_member(
    channel_id: str,
    body: SingleChannelMemberCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ChannelMemberResponse:
    """
    Grant access to a single user for the given channel id by email.

    This endpoint allows company admins or users with workspace management permissions to add a single
    member to a channel. It supports both creating new memberships and updating existing ones (upsert behavior).

    Input format:
    {
        "mail_id": "user@example.com",
        "role": "Admin",
        "permissions": {"can_manage": true}
    }

    Allowed roles: User, Admin (case-insensitive)

    Author: Pranhav Vimalbalaji
    Version: 1.0.0
    Last date modified: 13/08/2025
    """
    current_user = await get_current_user_required(request)

    # Validate channel_id as UUID
    channel_uuid = validate_uuid(channel_id, "channel ID")

    # Fetch channel
    stmt = select(Channel).where(Channel.id == channel_uuid)
    result = await db.execute(stmt)
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found")

    # Authorization: user must be company admin or able to manage within same company
    if not current_user.is_admin and str(current_user.company_id) != str(channel.company_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cross-company access denied")
    if not current_user.is_admin and not current_user.can_manage_workspace(str(channel.company_id)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    # KEY DIFFERENCE: This endpoint finds users by email (mail_id) instead of requiring user_id
    # This makes it easier to add users without needing to know their internal user ID
    # Find user by email_id (mail_id) - this allows adding users by email instead of requiring user_id
    user_stmt = select(User).where(
        and_(
            User.email_id == body.mail_id,
            User.company_id == channel.company_id,
            User.is_active == True
        )
    )
    user_result = await db.execute(user_stmt)
    user = user_result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with email {body.mail_id} not found or does not belong to this company"
        )

    # Check if user is already a member of this channel - implement upsert behavior
    # If user exists, update their role and permissions; if not, create new membership
    existing_stmt = select(ChannelMember).where(
        ChannelMember.channel_id == channel.id,
        ChannelMember.user_id == user.id,
    )
    existing_result = await db.execute(existing_stmt)
    existing = existing_result.scalar_one_or_none()

    if existing:
        # Update existing membership (upsert behavior)
        existing.role = body.role
        if body.permissions is not None:
            existing.permissions = body.permissions
        existing.is_active = True
        await audit_log_write(db, current_user.id, "channel.member_updated", "channel", channel_uuid, channel_id=channel_uuid, details={"member_id": str(user.id)})
        await db.commit()
        await db.refresh(existing)

        return ChannelMemberResponse(
            id=str(existing.id),
            channel_id=str(existing.channel_id),
            user_id=str(existing.user_id),
            role=existing.role,
            is_active=existing.is_active,
        )
    else:
        # Create new membership (user wasn't previously in this channel)
        member = ChannelMember(
            id=generate_channel_id(),  # Generate unique ID for new channel member
            channel_id=channel.id,
            user_id=user.id,
            role=body.role,
            permissions=body.permissions,
            is_active=True,
        )
        db.add(member)
        await audit_log_write(db, current_user.id, "channel.member_added", "channel", channel.id, channel_id=channel.id, details={"member_id": str(user.id)})
        await db.commit()
        await db.refresh(member)

        await notify_new_member(channel, user, current_user, body, db)

        return ChannelMemberResponse(
            id=str(member.id),
            channel_id=str(member.channel_id),
            user_id=str(member.user_id),
            role=member.role,
            is_active=member.is_active,
        )
