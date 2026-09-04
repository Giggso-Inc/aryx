"""
Realtime notification preference endpoints (mounted at /api/v1/notifications):
  GET  /realTimeNotificationSettings/{userId}/{channelId}  get_realtime_notification_settings
  POST /save                                                save_realtime_notification_settings
  PUT  /update                                              update_realtime_notification_settings
"""

import uuid

from fastapi import APIRouter, HTTPException, status, Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.user import User
from app.models.workspace import Workspace
from app.models.channel import Channel
from app.models.channel_member import ChannelMember
from app.models.realtime_notification import RealtimeNotification
from app.schemas.notification import (
    RealtimeNotificationResponse,
    RealtimeNotificationSaveRequest,
    RealtimeNotificationUpdateRequest,
)

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

    # Check if user is a member of the channel
    # Admin can access any channel, regular users must be in the same company
    if not current_user.is_admin:
        if str(target_user.company_id) != str(channel.company_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User does not belong to this channel's company"
            )

        # Check if current user can access this channel
        if str(current_user.company_id) != str(channel.company_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have access to this channel"
            )

        # Check if target user is a member of the channel (for non-public channels)
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

    # Check if notification settings already exist
    notification_stmt = select(RealtimeNotification).where(
        and_(
            RealtimeNotification.user_id == user_uuid,
            RealtimeNotification.channel_id == channel_uuid
        )
    )
    notification_result = await db.execute(notification_stmt)
    notification = notification_result.scalar_one_or_none()

    # If settings exist, return all values from database
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

    # If settings don't exist, return default values
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

    # Verify channel exists and belongs to the workspace
    channel_stmt = select(Channel).where(Channel.id == channel_uuid)
    channel_result = await db.execute(channel_stmt)
    channel = channel_result.scalar_one_or_none()

    if not channel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Channel with ID {request_data.channel_id} not found"
        )

    # Verify workspace exists
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

    # Check if notification settings already exist for this user and channel
    notification_stmt = select(RealtimeNotification).where(
        and_(
            RealtimeNotification.user_id == current_user.id,
            RealtimeNotification.channel_id == channel_uuid
        )
    )
    notification_result = await db.execute(notification_stmt)
    existing_notification = notification_result.scalar_one_or_none()

    # If data exists, update it; otherwise create new
    if existing_notification:
        # Update existing record
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
        # Create new record
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

    # Return the saved notification settings
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


@router.put("/update", response_model=RealtimeNotificationResponse)
async def update_realtime_notification_settings(
    request_data: RealtimeNotificationUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> RealtimeNotificationResponse:
    """
    Update realtime notification settings for the current user.

    Requires the primary key (id) from the database, along with channel_id,
    workspace_id, and all notification flags (both updated and non-updated).
    """
    # Get current authenticated user
    current_user = await get_current_user_required(request)

    # Validate UUIDs
    try:
        notification_id = uuid.UUID(request_data.id)
        workspace_uuid = uuid.UUID(request_data.workspace_id)
        channel_uuid = uuid.UUID(request_data.channel_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid UUID format for id, workspace_id, or channel_id"
        )

    # Find the notification record by primary key
    notification_stmt = select(RealtimeNotification).where(
        RealtimeNotification.id == notification_id
    )
    notification_result = await db.execute(notification_stmt)
    notification = notification_result.scalar_one_or_none()

    if not notification:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Notification settings with ID {request_data.id} not found"
        )

    # Verify the notification belongs to the current user
    if notification.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only update your own notification settings"
        )

    # Verify channel exists
    channel_stmt = select(Channel).where(Channel.id == channel_uuid)
    channel_result = await db.execute(channel_stmt)
    channel = channel_result.scalar_one_or_none()

    if not channel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Channel with ID {request_data.channel_id} not found"
        )

    # Verify workspace exists
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

    # Update the notification record with all provided values
    notification.workspace_id = workspace_uuid
    notification.channel_id = channel_uuid
    notification.is_notifications_enabled = request_data.is_notifications_enabled
    notification.apps_enabled = request_data.apps_enabled if request_data.apps_enabled else []
    notification.is_post_enabled = request_data.is_post_enabled
    notification.is_mention_enabled = request_data.is_mention_enabled
    notification.is_task_enabled = request_data.is_task_enabled
    notification.is_approval_enabled = request_data.is_approval_enabled
    notification.is_new_email_enabled = request_data.is_new_email_enabled
    notification.is_email_reply_enabled = request_data.is_email_reply_enabled

    await db.commit()
    await db.refresh(notification)

    # Return the updated notification settings
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
