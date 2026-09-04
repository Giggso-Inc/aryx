"""
POST /{channel_id}/members and GET /{channel_id}/members — single-user
membership grant and membership listing.

Split out of the original app/routes/channels.py (2,630 lines) — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5.
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, status, Request, Depends, Query
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.auth import generate_channel_id
from app.core.config import settings
from app.middleware.auth_middleware import get_current_user_required
from app.models.user import User
from app.models.channel import Channel
from app.models.channel_member import ChannelMember
from app.models.company import Company
from app.services.audit_service import log as audit_log_write
from app.services.email_service import email_service
from app.utils.channel_access import check_channel_access
from app.schemas.channel_member import (
    SingleChannelMemberCreate,
    ChannelMemberResponse,
    ChannelMemberUserList,
    ChannelMemberUserResponse,
)
from .helpers import validate_uuid, get_channel_admins

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

        # Email: Accsell/Zaptag → requirement flow only (added user, View Channel); others → previous flow (notify channel admins)
        try:
            # [DEBUG] Log raw body value so we can verify platform_name/platformName from request
            platform_name = body.platform_name or settings.PLATFORM_NAME
            platform_lower = str(platform_name or '').strip().lower()
            print(f"📧 [channel add-member] body.platform_name={body.platform_name!r}, resolved platform_name={platform_name!r}, platform_lower={platform_lower!r}, branch={'accsell/zaptag (to added user)' if platform_lower in ('accsell', 'zaptag') else 'admin (to admins)'}")
            if platform_lower in ('accsell', 'zaptag'):
                # Accsell/Zaptag: send only to the added user with "You have been added" + View Channel button (requirement flow)
                notification_data_user = {
                    'channel_id': str(channel.id),
                    'channel_name': channel.name,
                    'user_name': user.name or user.email_id.split('@')[0],
                    'user_email': user.email_id,
                    'user_role': body.role,
                    'added_by': current_user.name or current_user.email_id.split('@')[0],
                    'platform_name': platform_name,
                    'send_to_added_user': True
                }
                # View Channel URL: use SHAY_PLATFORM_URL when platform is Accsell and set, else PLATFORM_URL
                base_url = (settings.SHAY_PLATFORM_URL or settings.PLATFORM_URL) if platform_lower == 'accsell' else settings.PLATFORM_URL
                # [DEBUG] Confirm payload before calling email service
                print(f"📧 [channel add-member] Sending to added user: to_emails=[{user.email_id}], notification_data keys={list(notification_data_user.keys())}, send_to_added_user={notification_data_user.get('send_to_added_user')!r}, platform_url={base_url!r}")
                email_sent_user = email_service.send_channel_member_notification(
                    to_emails=[user.email_id],
                    notification_data=notification_data_user,
                    platform_url=base_url
                )
                if email_sent_user:
                    print(f"✅ Channel member notification (added user) sent to {user.email_id}")
                else:
                    print(f"⚠️ Channel member notification (added user) failed to send")
            else:
                # Previous flow: send email notification to channel admins (unchanged for non-Accsell/Zaptag; no send_to_added_user)
                print(f"📧 Preparing to notify channel admins about new member {user.email_id}...")
                channel_admins = await get_channel_admins(channel.id, db)
                if channel_admins:
                    admin_emails = [admin.email_id for admin in channel_admins if admin.email_id]
                    if admin_emails:
                        # Do not add send_to_added_user here; email_service uses its absence for admin subject/body
                        notification_data = {
                            'channel_name': channel.name,
                            'user_name': user.name or user.email_id.split('@')[0],
                            'user_email': user.email_id,
                            'user_role': body.role,
                            'added_by': current_user.name or current_user.email_id.split('@')[0],
                            'platform_name': platform_name
                        }
                        email_sent = email_service.send_channel_member_notification(
                            to_emails=admin_emails,
                            notification_data=notification_data,
                            platform_url=settings.PLATFORM_URL
                        )
                        if email_sent:
                            print(f"✅ Channel member notification emails sent successfully to {len(admin_emails)} admins")
                        else:
                            print(f"⚠️ Some channel member notification emails failed to send")
                else:
                    print(f"ℹ️ No channel admins found to notify")
        except Exception as email_error:
            # Log email error but don't fail the member addition
            print(f"⚠️ Error sending channel member notification (non-critical): {email_error}")
            import traceback
            print(f"📋 Email error traceback: {traceback.format_exc()}")

        return ChannelMemberResponse(
            id=str(member.id),
            channel_id=str(member.channel_id),
            user_id=str(member.user_id),
            role=member.role,
            is_active=member.is_active,
        )


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

    # Build base query joining users and company for richer info
    from app.models.user import User

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
