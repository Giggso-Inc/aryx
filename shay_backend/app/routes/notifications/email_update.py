"""
PUT /emailnotifysettings/update — update_email_notify_settings
(mounted at /api/v1/notifications).
"""

import uuid

from fastapi import APIRouter, HTTPException, status, Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.email_notify_settings import EmailNotifySettings
from app.schemas.notification import (
    EmailNotifySettingsResponse,
    EmailNotifySettingsUpdateRequest,
)
from app.routes.notifications.email_helpers import VALID_ROUTINES

router = APIRouter()


@router.put("/emailnotifysettings/update", response_model=EmailNotifySettingsResponse)
async def update_email_notify_settings(
    request_data: EmailNotifySettingsUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> EmailNotifySettingsResponse:
    """
    Update email notification settings for a user.

    Requires the primary key (id) and resource_id in the request.
    Updates the record based on both id and resource_id.

    Routine values: 15 mins, 30 mins, 45 mins, 1 hour (60), 4 hours (240),
    8 hours (480), 12 hours (720), 24 hours (1440)
    """
    # Get current authenticated user
    current_user = await get_current_user_required(request)

    # Validate UUIDs
    try:
        notification_id = uuid.UUID(request_data.id)
        resource_uuid = uuid.UUID(request_data.resource_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid UUID format for id or resource_id"
        )

    # Validate routine value if provided (must be one of the allowed values)
    if request_data.routine is not None and request_data.routine not in VALID_ROUTINES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid routine value. Must be one of: {VALID_ROUTINES} (in minutes)"
        )

    # Find the notification record by primary key and resource_id
    notification_stmt = select(EmailNotifySettings).where(
        and_(
            EmailNotifySettings.id == notification_id,
            EmailNotifySettings.resource_id == resource_uuid
        )
    )
    notification_result = await db.execute(notification_stmt)
    notification = notification_result.scalar_one_or_none()

    if not notification:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Email notification settings with ID {request_data.id} and resource_id {request_data.resource_id} not found"
        )

    # Update the notification record with all provided values
    notification.resource_id = resource_uuid
    notification.routine = request_data.routine
    notification.is_notification_enabled = request_data.is_notification_enabled
    notification.post_enabled = request_data.post_enabled
    notification.app_enabled = request_data.app_enabled
    notification.blocker_enabled = request_data.blocker_enabled
    notification.approval_pending_enabled = request_data.approval_pending_enabled
    notification.meeting_enabled = request_data.meeting_enabled
    notification.task_enabled = request_data.task_enabled
    notification.mention_enabled = request_data.mention_enabled
    notification.reply_enabled = request_data.reply_enabled
    notification.chat_enabled = request_data.chat_enabled
    notification.friend_enabled = request_data.friend_enabled
    notification.updated_by = current_user.id

    await db.commit()
    await db.refresh(notification)

    # Return the updated notification settings
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
