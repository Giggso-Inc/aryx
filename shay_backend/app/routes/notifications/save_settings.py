"""
POST /save (mounted at /api/v1/notifications). Split out of the former
realtime.py (Raven style-compliance pass,
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, wave B); see
notifications/__init__.py for how the pieces recombine.
"""

import uuid

from fastapi import APIRouter, HTTPException, status, Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.workspace import Workspace
from app.models.channel import Channel
from app.models.realtime_notification import RealtimeNotification
from app.schemas.notification import (
    RealtimeNotificationResponse,
    RealtimeNotificationSaveRequest,
)

router = APIRouter()


@router.post("/save", response_model=RealtimeNotificationResponse)
async def save_realtime_notification_settings(
    request_data: RealtimeNotificationSaveRequest,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> RealtimeNotificationResponse:
    """
    Save realtime notification settings for the current user in a channel.

    Before saving, checks if data already exists for the user and channel.
    If data exists, updates it. If not, creates a new record.

    Payload includes workspace_id, channel_id, and all notification flags.
    """
    # Get current authenticated user
    current_user = await get_current_user_required(request)

    # Validate UUIDs
    try:
        workspace_uuid = uuid.UUID(request_data.workspace_id)
        channel_uuid = uuid.UUID(request_data.channel_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid UUID format for workspace_id or channel_id"
        )

    channel_stmt = select(Channel).where(Channel.id == channel_uuid)
    channel_result = await db.execute(channel_stmt)
    channel = channel_result.scalar_one_or_none()

    if not channel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Channel with ID {request_data.channel_id} not found"
        )

    workspace_stmt = select(Workspace).where(Workspace.id == workspace_uuid)
    workspace_result = await db.execute(workspace_stmt)
    workspace = workspace_result.scalar_one_or_none()

    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workspace with ID {request_data.workspace_id} not found"
        )

    # Verify channel belongs to the workspace
    if str(channel.workspace_id) != str(workspace_uuid):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Channel does not belong to the specified workspace"
        )

    # Check if user can access this channel
    if not current_user.is_admin:
        if str(current_user.company_id) != str(channel.company_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have access to this channel"
            )

    notification_stmt = select(RealtimeNotification).where(
        and_(
            RealtimeNotification.user_id == current_user.id,
            RealtimeNotification.channel_id == channel_uuid
        )
    )
    notification_result = await db.execute(notification_stmt)
    existing_notification = notification_result.scalar_one_or_none()

    if existing_notification:
        existing_notification.workspace_id = workspace_uuid
        existing_notification.channel_id = channel_uuid
        existing_notification.is_notifications_enabled = request_data.is_notifications_enabled
        existing_notification.apps_enabled = request_data.apps_enabled if request_data.apps_enabled else []
        existing_notification.is_post_enabled = request_data.is_post_enabled
        existing_notification.is_mention_enabled = request_data.is_mention_enabled
        existing_notification.is_task_enabled = request_data.is_task_enabled
        existing_notification.is_approval_enabled = request_data.is_approval_enabled
        existing_notification.is_new_email_enabled = request_data.is_new_email_enabled
        existing_notification.is_email_reply_enabled = request_data.is_email_reply_enabled

        await db.commit()
        await db.refresh(existing_notification)

        notification = existing_notification
    else:
        notification = RealtimeNotification(
            id=uuid.uuid4(),
            user_id=current_user.id,
            workspace_id=workspace_uuid,
            channel_id=channel_uuid,
            is_notifications_enabled=request_data.is_notifications_enabled,
            apps_enabled=request_data.apps_enabled if request_data.apps_enabled else [],
            is_post_enabled=request_data.is_post_enabled,
            is_mention_enabled=request_data.is_mention_enabled,
            is_task_enabled=request_data.is_task_enabled,
            is_approval_enabled=request_data.is_approval_enabled,
            is_new_email_enabled=request_data.is_new_email_enabled,
            is_email_reply_enabled=request_data.is_email_reply_enabled
        )

        db.add(notification)
        await db.commit()
        await db.refresh(notification)

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
