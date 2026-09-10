"""
Channel-membership lookup shared by the assignment/reassignment
notification dispatchers. Split out of the former notifications_dispatch.py
(Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md) to keep every resulting
file under the 150-line target.
"""

from uuid import UUID
from typing import List

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.models.user import User
from app.models.channel_member import ChannelMember
from app.models.realtime_notification import RealtimeNotification


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
