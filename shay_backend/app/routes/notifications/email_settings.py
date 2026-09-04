"""
Email notification settings + scheduler-trigger endpoints (mounted at
/api/v1/notifications):
  POST /emailnotifysettings/save          save_email_notify_settings
  PUT  /emailnotifysettings/update        update_email_notify_settings
  GET  /emailnotifysettings/{userId}      get_email_notify_settings
  POST /emailnotifysettings/test/trigger  trigger_daily_summary_scheduler_test

The scheduler-trigger endpoint is grouped here (rather than its own file)
because it is a thin manual-test hook for the same email-notification
subsystem these three CRUD endpoints manage, not an independent resource.
"""

import uuid

from fastapi import APIRouter, HTTPException, status, Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.user import User
from app.models.email_notify_settings import EmailNotifySettings
from app.schemas.notification import (
    EmailNotifySettingsResponse,
    EmailNotifySettingsSaveRequest,
    EmailNotifySettingsUpdateRequest,
)

router = APIRouter()

VALID_ROUTINES = [15, 30, 45, 60, 240, 480, 720, 1440]


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


@router.post("/emailnotifysettings/test/trigger")
async def trigger_daily_summary_scheduler_test(
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> dict:
    """
    Manually trigger the daily summary email scheduler for testing.

    This endpoint allows you to manually trigger the scheduler to test
    if emails are being sent correctly.
    """
    from app.services.daily_summary_scheduler import daily_summary_scheduler

    # Get current authenticated user (optional - for logging)
    try:
        current_user = await get_current_user_required(request)
        user_info = f"Triggered by user: {current_user.email_id}"
    except:
        user_info = "Triggered anonymously"

    try:
        if not daily_summary_scheduler.is_running:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Scheduler is not running"
            )

        # Manually trigger the process
        await daily_summary_scheduler.process_daily_summaries()

        return {
            "status": "success",
            "message": "Scheduler triggered manually - check logs for details",
            "triggered_by": user_info
        }
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        error_traceback = traceback.format_exc()
        print(f"❌ Error triggering scheduler: {error_traceback}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error triggering scheduler: {str(e)}"
        )
