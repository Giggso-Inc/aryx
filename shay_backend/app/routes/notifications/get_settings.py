"""
GET /realTimeNotificationSettings/{userId}/{channelId} (mounted at
/api/v1/notifications). Split out of the former realtime.py (Raven
style-compliance pass, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md,
wave B); see notifications/__init__.py for how the pieces recombine.
"""

import uuid

from fastapi import APIRouter, HTTPException, status, Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.user import User
from app.models.channel import Channel
from app.models.channel_member import ChannelMember
from app.models.realtime_notification import RealtimeNotification
from app.schemas.notification import RealtimeNotificationResponse

router = APIRouter()


@router.get("/realTimeNotificationSettings/{userId}/{channelId}", response_model=RealtimeNotificationResponse)
async def get_realtime_notification_settings(
    userId: str,
    channelId: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> RealtimeNotificationResponse:
    """
    Get realtime notification settings for a user in a channel.

    If settings don't exist, returns default values:
    - is_notifications_enabled: true
    - is_mention_enabled: true
    - All other notification types: false
    - workspace_id and channel_id: null
    - id: null
    - created_at and updated_at: not included
    """
    # Get current authenticated user
    current_user = await get_current_user_required(request)

    # Validate UUIDs
    try:
        user_uuid = uuid.UUID(userId)
        channel_uuid = uuid.UUID(channelId)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid UUID format for userId or channelId"
        )

    # Verify the target user exists
    user_stmt = select(User).where(User.id == user_uuid)
    user_result = await db.execute(user_stmt)
    target_user = user_result.scalar_one_or_none()

    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with ID {userId} not found"
        )

    # Verify channel exists
    channel_stmt = select(Channel).where(Channel.id == channel_uuid)
    channel_result = await db.execute(channel_stmt)
    channel = channel_result.scalar_one_or_none()

    if not channel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Channel with ID {channelId} not found"
        )

    # Admin can access any channel, regular users must be in the same company
    if not current_user.is_admin:
        if str(target_user.company_id) != str(channel.company_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User does not belong to this channel's company"
            )

        if str(current_user.company_id) != str(channel.company_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have access to this channel"
            )

        if not channel.is_public:
            member_stmt = select(ChannelMember).where(
                and_(
                    ChannelMember.channel_id == channel_uuid,
                    ChannelMember.user_id == user_uuid,
                    ChannelMember.is_active == True
                )
            )
            member_result = await db.execute(member_stmt)
            membership = member_result.scalar_one_or_none()

            if not membership:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="User is not a member of this channel"
                )

    notification_stmt = select(RealtimeNotification).where(
        and_(
            RealtimeNotification.user_id == user_uuid,
            RealtimeNotification.channel_id == channel_uuid
        )
    )
    notification_result = await db.execute(notification_stmt)
    notification = notification_result.scalar_one_or_none()

    if notification:
        return RealtimeNotificationResponse(
            id=str(notification.id),
            user_id=str(notification.user_id),
            workspace_id=str(notification.workspace_id),
            channel_id=str(notification.channel_id),
            is_notifications_enabled=notification.is_notifications_enabled,
            apps_enabled=notification.apps_enabled if notification.apps_enabled else [],
            is_post_enabled=notification.is_post_enabled,
            is_mention_enabled=notification.is_mention_enabled,
            is_task_enabled=notification.is_task_enabled,
            is_approval_enabled=notification.is_approval_enabled,
            is_new_email_enabled=notification.is_new_email_enabled,
            is_email_reply_enabled=notification.is_email_reply_enabled,
            created_at=notification.created_at,
            updated_at=notification.updated_at
        )

    return RealtimeNotificationResponse(
        id=None,
        user_id=str(user_uuid),
        workspace_id=None,
        channel_id=None,
        is_notifications_enabled=True,  # Enabled because mention is enabled
        apps_enabled=[],  # Empty list by default
        is_post_enabled=False,
        is_mention_enabled=True,  # Only mention enabled by default
        is_task_enabled=False,
        is_approval_enabled=False,
        is_new_email_enabled=False,
        is_email_reply_enabled=False
    )
