"""
Background-task entry points for task assignment/reassignment notifications
(scheduled via FastAPI's BackgroundTasks from crud.py and assignment.py),
plus the channel-membership lookup they share.

Kept together (get_channel_members_with_task_notifications_enabled,
process_task_reassignment_notifications, process_task_assignment_notifications):
the two process_* functions are near-identical mirrors of each other (fetch
actor/target/channel, resolve notification-enabled members, send one email
per member) and both call the membership lookup directly — splitting the
lookup into its own module would add an import for no isolation benefit.
"""

from uuid import UUID
from typing import List

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.core.database import AsyncSessionLocal
from app.models.user import User
from app.models.channel import Channel
from app.models.channel_member import ChannelMember
from app.models.realtime_notification import RealtimeNotification

from .notifications_email import (
    send_task_assignment_notification_email,
    send_task_reassignment_notification_email,
)


async def get_channel_members_with_task_notifications_enabled(
    channel_id: UUID,
    task_creator_id: UUID,
    db: AsyncSession
) -> List[User]:
    """
    Get all channel members who have task notifications enabled.
    Excludes the task creator.

    Logic:
    - Get all active channel members
    - For each member, check gg_realtime_notification table
    - Only include if:
      1. Data exists in table
      2. is_notifications_enabled = true
      3. is_task_enabled = true
    - Exclude task creator

    Args:
        channel_id: Channel ID
        task_creator_id: User ID who created the task (will be excluded)
        db: Database session

    Returns:
        List of User objects who have task notifications enabled
    """
    # Get all active channel members
    channel_members_stmt = select(ChannelMember).where(
        and_(
            ChannelMember.channel_id == channel_id,
            ChannelMember.is_active == True
        )
    )
    channel_members_result = await db.execute(channel_members_stmt)
    channel_members = channel_members_result.scalars().all()

    if not channel_members:
        return []

    # Get user IDs from channel members
    member_user_ids = [member.user_id for member in channel_members]

    # Get notification preferences for all members in this channel
    notification_prefs_stmt = select(RealtimeNotification).where(
        and_(
            RealtimeNotification.channel_id == channel_id,
            RealtimeNotification.user_id.in_(member_user_ids)
        )
    )
    notification_prefs_result = await db.execute(notification_prefs_stmt)
    notification_prefs = notification_prefs_result.scalars().all()

    # Create a map of user_id -> notification preference
    notification_map = {pref.user_id: pref for pref in notification_prefs}

    # Filter members who have notifications enabled
    enabled_user_ids = []
    for member in channel_members:
        # Skip task creator
        if member.user_id == task_creator_id:
            continue

        # Check if notification preference exists
        notification_pref = notification_map.get(member.user_id)

        # Only send if data exists AND both flags are enabled
        if notification_pref:
            if notification_pref.is_notifications_enabled and notification_pref.is_task_enabled:
                enabled_user_ids.append(member.user_id)

    if not enabled_user_ids:
        return []

    # Get user details for enabled members
    users_stmt = select(User).where(User.id.in_(enabled_user_ids))
    users_result = await db.execute(users_stmt)
    users = users_result.scalars().all()

    return list(users)


async def process_task_reassignment_notifications(
    reassigner_id: str,
    reassigned_user_id: str,
    channel_id: str,
    redirect_url: str,
    notification_settings_url: str
) -> None:
    """
    Process task reassignment notifications for channel members.
    This function creates its own database session for background processing.

    Args:
        reassigner_id: UUID string of the user who reassigned the task
        reassigned_user_id: UUID string of the user reassigned to the task
        channel_id: UUID string of the channel where task was reassigned
        redirect_url: Pre-constructed URL to redirect to view the task
        notification_settings_url: Pre-constructed URL to notification settings page
    """
    # Create new session for background task
    async with AsyncSessionLocal() as db:
        try:
            # Get reassigner
            reassigner_stmt = select(User).where(User.id == UUID(reassigner_id))
            reassigner_result = await db.execute(reassigner_stmt)
            reassigner = reassigner_result.scalar_one_or_none()

            if not reassigner:
                print(f"⚠️ Reassigner not found: {reassigner_id}")
                return

            # Get reassigned user
            reassigned_stmt = select(User).where(User.id == UUID(reassigned_user_id))
            reassigned_result = await db.execute(reassigned_stmt)
            reassigned_user = reassigned_result.scalar_one_or_none()

            if not reassigned_user:
                print(f"⚠️ Reassigned user not found: {reassigned_user_id}")
                return

            # Get channel
            channel_stmt = select(Channel).where(Channel.id == UUID(channel_id))
            channel_result = await db.execute(channel_stmt)
            channel = channel_result.scalar_one_or_none()

            if not channel:
                print(f"⚠️ Channel not found: {channel_id}")
                return

            # Get channel members with task notifications enabled
            enabled_members = await get_channel_members_with_task_notifications_enabled(
                channel.id,
                reassigner.id,
                db
            )

            if not enabled_members:
                print(f"ℹ️ No channel members with task notifications enabled for channel {channel_id}")
                return

            # Send notification to each enabled member with pre-constructed URLs
            for member in enabled_members:
                await send_task_reassignment_notification_email(
                    member,
                    reassigner,
                    reassigned_user,
                    channel,
                    redirect_url,
                    notification_settings_url,
                    db
                )

        except Exception as e:
            print(f"❌ Error processing task reassignment notifications: {e}")
            import traceback
            print(f"📋 Error traceback: {traceback.format_exc()}")


async def process_task_assignment_notifications(
    task_creator_id: str,
    assigned_user_id: str,
    channel_id: str,
    task_title: str,
    redirect_url: str,
    notification_settings_url: str
) -> None:
    """
    Process task assignment notifications for channel members.
    This function creates its own database session for background processing.

    Args:
        task_creator_id: UUID string of the user who created the task
        assigned_user_id: UUID string of the user assigned to the task
        channel_id: UUID string of the channel where task was created
        task_title: Title of the task
        redirect_url: Pre-constructed URL to redirect to view the task
        notification_settings_url: Pre-constructed URL to notification settings page
    """
    # Create new session for background task
    async with AsyncSessionLocal() as db:
        try:
            # Get task creator
            creator_stmt = select(User).where(User.id == UUID(task_creator_id))
            creator_result = await db.execute(creator_stmt)
            task_creator = creator_result.scalar_one_or_none()

            if not task_creator:
                print(f"⚠️ Task creator not found: {task_creator_id}")
                return

            # Get assigned user
            assigned_stmt = select(User).where(User.id == UUID(assigned_user_id))
            assigned_result = await db.execute(assigned_stmt)
            assigned_user = assigned_result.scalar_one_or_none()

            if not assigned_user:
                print(f"⚠️ Assigned user not found: {assigned_user_id}")
                return

            # Get channel
            channel_stmt = select(Channel).where(Channel.id == UUID(channel_id))
            channel_result = await db.execute(channel_stmt)
            channel = channel_result.scalar_one_or_none()

            if not channel:
                print(f"⚠️ Channel not found: {channel_id}")
                return

            # Get channel members with task notifications enabled
            enabled_members = await get_channel_members_with_task_notifications_enabled(
                channel.id,
                task_creator.id,
                db
            )

            if not enabled_members:
                print(f"ℹ️ No channel members with task notifications enabled for channel {channel_id}")
                return

            # Send notification to each enabled member with pre-constructed URLs
            for member in enabled_members:
                await send_task_assignment_notification_email(
                    member,
                    task_creator,
                    assigned_user,
                    channel,
                    task_title,
                    redirect_url,
                    notification_settings_url,
                    db
                )

        except Exception as e:
            print(f"❌ Error processing task assignment notifications: {e}")
            import traceback
            print(f"📋 Error traceback: {traceback.format_exc()}")
