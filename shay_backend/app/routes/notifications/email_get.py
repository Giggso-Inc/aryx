"""
GET /emailnotifysettings/{userId} — get_email_notify_settings
(mounted at /api/v1/notifications).
"""

import uuid

from fastapi import APIRouter, HTTPException, status, Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.user import User
from app.models.email_notify_settings import EmailNotifySettings
from app.schemas.notification import EmailNotifySettingsResponse

router = APIRouter()


@router.get("/emailnotifysettings/{userId}", response_model=EmailNotifySettingsResponse)
async def get_email_notify_settings(
    userId: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> EmailNotifySettingsResponse:
    """
    Get email notification settings for a user by userId (resource_id).

    Returns the email notification settings for the specified user.
    If no settings exist, returns a response with default values.
    """
    # Get current authenticated user
    current_user = await get_current_user_required(request)

    # Validate UUID
    try:
        user_uuid = uuid.UUID(userId)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid UUID format for userId"
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

    # Check if notification settings exist for this user
    notification_stmt = select(EmailNotifySettings).where(
        EmailNotifySettings.resource_id == user_uuid
    )
    notification_result = await db.execute(notification_stmt)
    notification = notification_result.scalar_one_or_none()

    # If settings exist, return all values from database
    if notification:
        return EmailNotifySettingsResponse(
            id=str(notification.id),
            resource_id=str(notification.resource_id) if notification.resource_id else None,
            routine=notification.routine,
            is_notification_enabled=notification.is_notification_enabled,
            post_enabled=notification.post_enabled,
            app_enabled=notification.app_enabled,
            blocker_enabled=notification.blocker_enabled,
            approval_pending_enabled=notification.approval_pending_enabled,
            meeting_enabled=notification.meeting_enabled,
            task_enabled=notification.task_enabled,
            mention_enabled=notification.mention_enabled,
            reply_enabled=notification.reply_enabled,
            chat_enabled=notification.chat_enabled,
            friend_enabled=notification.friend_enabled,
            created_by=str(notification.created_by) if notification.created_by else None,
            updated_by=str(notification.updated_by) if notification.updated_by else None,
            created_time=notification.created_time,
            updated_time=notification.updated_time,
            last_email_notify_time=notification.last_email_notify_time
        )

    # If settings don't exist, return default values
    return EmailNotifySettingsResponse(
        id=None,
        resource_id=str(user_uuid),
        routine=None,
        is_notification_enabled=0,
        post_enabled=0,
        app_enabled=0,
        blocker_enabled=0,
        approval_pending_enabled=0,
        meeting_enabled=0,
        task_enabled=0,
        mention_enabled=0,
        reply_enabled=0,
        chat_enabled=0,
        friend_enabled=0,
        created_by=None,
        updated_by=None,
        created_time=None,
        updated_time=None,
        last_email_notify_time=None
    )
