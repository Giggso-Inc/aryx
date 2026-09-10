"""
POST /emailnotifysettings/save — save_email_notify_settings
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
from app.schemas.notification import (
    EmailNotifySettingsResponse,
    EmailNotifySettingsSaveRequest,
)
from app.routes.notifications.email_helpers import VALID_ROUTINES

router = APIRouter()


@router.post("/emailnotifysettings/save", response_model=EmailNotifySettingsResponse)
async def save_email_notify_settings(
    request_data: EmailNotifySettingsSaveRequest,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> EmailNotifySettingsResponse:
    """
    Save email notification settings for a user.

    Before saving, checks if data already exists for the resource_id.
    If data exists, updates it. If not, creates a new record.

    Routine values: 15 mins, 30 mins, 45 mins, 1 hour (60), 4 hours (240),
    8 hours (480), 12 hours (720), 24 hours (1440)
    """
    # Get current authenticated user
    current_user = await get_current_user_required(request)

    # Validate resource_id UUID
    try:
        resource_uuid = uuid.UUID(request_data.resource_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid UUID format for resource_id"
        )

    # Validate routine value if provided (must be one of the allowed values)
    if request_data.routine is not None and request_data.routine not in VALID_ROUTINES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid routine value. Must be one of: {VALID_ROUTINES} (in minutes)"
        )

    # Verify the user exists
    user_stmt = select(User).where(User.id == resource_uuid)
    user_result = await db.execute(user_stmt)
    target_user = user_result.scalar_one_or_none()

    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with ID {request_data.resource_id} not found"
        )

    # Check if notification settings already exist for this resource_id
    notification_stmt = select(EmailNotifySettings).where(
        EmailNotifySettings.resource_id == resource_uuid
    )
    notification_result = await db.execute(notification_stmt)
    existing_notification = notification_result.scalar_one_or_none()

    # If data exists, update it; otherwise create new
    if existing_notification:
        # Update existing record
        existing_notification.resource_id = resource_uuid
        existing_notification.routine = request_data.routine
        existing_notification.is_notification_enabled = request_data.is_notification_enabled
        existing_notification.post_enabled = request_data.post_enabled
        existing_notification.app_enabled = request_data.app_enabled
        existing_notification.blocker_enabled = request_data.blocker_enabled
        existing_notification.approval_pending_enabled = request_data.approval_pending_enabled
        existing_notification.meeting_enabled = request_data.meeting_enabled
        existing_notification.task_enabled = request_data.task_enabled
        existing_notification.mention_enabled = request_data.mention_enabled
        existing_notification.reply_enabled = request_data.reply_enabled
        existing_notification.chat_enabled = request_data.chat_enabled
        existing_notification.friend_enabled = request_data.friend_enabled
        existing_notification.updated_by = current_user.id

        await db.commit()
        await db.refresh(existing_notification)

        notification = existing_notification
    else:
        # Create new record
        notification = EmailNotifySettings(
            id=uuid.uuid4(),
            resource_id=resource_uuid,
            routine=request_data.routine,
            is_notification_enabled=request_data.is_notification_enabled,
            post_enabled=request_data.post_enabled,
            app_enabled=request_data.app_enabled,
            blocker_enabled=request_data.blocker_enabled,
            approval_pending_enabled=request_data.approval_pending_enabled,
            meeting_enabled=request_data.meeting_enabled,
            task_enabled=request_data.task_enabled,
            mention_enabled=request_data.mention_enabled,
            reply_enabled=request_data.reply_enabled,
            chat_enabled=request_data.chat_enabled,
            friend_enabled=request_data.friend_enabled,
            created_by=current_user.id,
            updated_by=current_user.id
        )

        db.add(notification)
        await db.commit()
        await db.refresh(notification)

    # Return the saved notification settings
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
