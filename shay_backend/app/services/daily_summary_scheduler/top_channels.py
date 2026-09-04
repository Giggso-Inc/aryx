"""
get_top_channels: per-channel notification counts, ranked to the top 5, for
the summary email's channel table.

Stated exception (well over the ~150-line-per-file target on its own): like
collect_notification_counts in counts.py, this is one query-building pass
per channel that shares the same time-window/email-channel setup computed
once up front; splitting the per-type count blocks out would duplicate that
shared setup rather than isolate an independently reusable concern.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List
import uuid

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.approval import Approval
from app.models.channel import Channel
from app.models.channel_member import ChannelMember
from app.models.email_notify_settings import EmailNotifySettings
from app.models.message import Message
from app.models.task import Task
from app.models.user import User

from .time_utils import datetime_for_db


class TopChannelsMixin:
    """get_top_channels: per-channel counts, ranked and formatted for the template."""

    async def get_top_channels(
        self,
        user_id: uuid.UUID,
        email_settings: EmailNotifySettings,
        db: AsyncSession
    ) -> List[Dict[str, Any]]:
        """
        Get top 5 channels with notification counts for the user.
        Channels are ranked by total notification count based on enabled notification types.

        Args:
            user_id: User ID
            email_settings: Email notification settings to determine which notifications to count
            db: Database session

        Returns:
            List of dictionaries with channel_name, channel_url, and notification_count
        """
        # Get user details for mention detection
        user_stmt = select(User).where(User.id == user_id)
        user_result = await db.execute(user_stmt)
        user = user_result.scalar_one_or_none()
        user_name = user.name if user and user.name else None

        # Get user's channel memberships
        channel_memberships_stmt = select(ChannelMember.channel_id).where(
            and_(
                ChannelMember.user_id == user_id,
                ChannelMember.is_active == True
            )
        )
        channel_result = await db.execute(channel_memberships_stmt)
        user_channel_ids = [row[0] for row in channel_result.all()]

        if not user_channel_ids:
            return []

        # Determine time window based on routine interval (in minutes)
        # routine values: 15, 30, 45, 60, 240, 480, 720, 1440 (minutes)
        now = datetime.now(timezone.utc)
        if email_settings.routine:
            # Use routine interval from current time
            time_window_start = datetime_for_db(now - timedelta(minutes=email_settings.routine))
        else:
            # Default to 24 hours if no routine set
            time_window_start = datetime_for_db(now - timedelta(hours=24))

        # Get email channel IDs - channels that have messages with message_type='email'
        email_channels_stmt = select(Message.channel_id).where(
            and_(
                Message.channel_id.in_(user_channel_ids),
                Message.message_type == 'email'
            )
        ).distinct()
        email_channels_result = await db.execute(email_channels_stmt)
        email_channel_ids = [row[0] for row in email_channels_result.all()]

        # Get channels with notification counts based on enabled types
        channels_stmt = select(
            Channel.id,
            Channel.name
        ).where(
            Channel.id.in_(user_channel_ids)
        )

        channels_result = await db.execute(channels_stmt)
        channels_data = []

        for channel_id, channel_name in channels_result.all():
            notification_count = 0

            # Count mentions if enabled (using user's name in content)
            if email_settings.mention_enabled == 1 and user_name:
                mentions_stmt = select(func.count(Message.id)).where(
                    and_(
                        Message.channel_id == channel_id,
                        Message.created_at >= time_window_start,
                        Message.message_type == 'user',
                        Message.content.ilike(f'%@{user_name}%')  # Check for @username in content
                    )
                )
                mentions_result = await db.execute(mentions_stmt)
                notification_count += mentions_result.scalar() or 0

            # Count posts if enabled (regular posts + email conversations)
            if email_settings.post_enabled == 1:
                # Count regular posts (user messages, excluding user's own)
                posts_stmt = select(func.count(Message.id)).where(
                    and_(
                        Message.channel_id == channel_id,
                        Message.created_at >= time_window_start,
                        Message.message_type == 'user',
                        Message.user_id != user_id  # Exclude user's own messages
                    )
                )
                posts_result = await db.execute(posts_stmt)
                notification_count += posts_result.scalar() or 0

                # Count email conversations (message_type = 'email')
                email_conversations_stmt = select(func.count(Message.id)).where(
                    and_(
                        Message.channel_id == channel_id,
                        Message.created_at >= time_window_start,
                        Message.message_type == 'email'
                    )
                )
                email_conv_result = await db.execute(email_conversations_stmt)
                notification_count += email_conv_result.scalar() or 0

            # Count replies if enabled (only in email channels)
            if email_settings.reply_enabled == 1 and channel_id in email_channel_ids:
                # Get threads in this email channel where user has messages
                user_email_threads_stmt = select(Message.thread_id).where(
                    and_(
                        Message.user_id == user_id,
                        Message.channel_id == channel_id
                    )
                ).distinct()
                user_email_threads_result = await db.execute(user_email_threads_stmt)
                user_email_thread_ids = [row[0] for row in user_email_threads_result.all()]

                if user_email_thread_ids:
                    # Count replies in these email threads (excluding user's own)
                    replies_stmt = select(func.count(Message.id)).where(
                        and_(
                            Message.thread_id.in_(user_email_thread_ids),
                            Message.created_at >= time_window_start,
                            Message.user_id != user_id,  # Exclude user's own replies
                            Message.channel_id == channel_id
                        )
                    )
                    replies_result = await db.execute(replies_stmt)
                    notification_count += replies_result.scalar() or 0

            # Count tasks if enabled (tasks assigned to user in this channel)
            if email_settings.task_enabled == 1:
                tasks_stmt = select(func.count(Task.id)).where(
                    and_(
                        Task.assigned_to == user_id,  # Only tasks assigned to user
                        Task.channel_id == channel_id,  # In this channel
                        Task.created_at >= time_window_start,
                        Task.status != 'Close'
                    )
                )
                tasks_result = await db.execute(tasks_stmt)
                notification_count += tasks_result.scalar() or 0

            # Count approvals if enabled (approvals pending for user in this channel)
            if email_settings.approval_pending_enabled == 1:
                approvals_stmt = select(func.count(Approval.id)).where(
                    and_(
                        Approval.approver_user_id == user_id,  # Check approver_user_id column
                        Approval.channel_id == channel_id,  # In this channel
                        Approval.status == 'pending',
                        Approval.created_at >= time_window_start
                    )
                )
                approvals_result = await db.execute(approvals_stmt)
                notification_count += approvals_result.scalar() or 0

            # Count blockers if enabled (blocker tasks assigned to user in this channel)
            if email_settings.blocker_enabled == 1:
                blockers_stmt = select(func.count(Task.id)).where(
                    and_(
                        Task.assigned_to == user_id,  # Only tasks assigned to user
                        Task.channel_id == channel_id,  # In this channel
                        Task.priority == 'Blocker',
                        Task.status != 'Close',
                        Task.created_at >= time_window_start
                    )
                )
                blockers_result = await db.execute(blockers_stmt)
                notification_count += blockers_result.scalar() or 0

            # Only include channels with notifications
            if notification_count > 0:
                channels_data.append({
                    'channel_id': channel_id,
                    'channel_name': channel_name or 'Unnamed Channel',
                    'notification_count': notification_count
                })

        # Sort by notification count (descending) and get top 5
        channels_data.sort(key=lambda x: x['notification_count'], reverse=True)
        top_channels = channels_data[:5]

        # Format for template
        result = []
        for channel in top_channels:
            channel_url = f"{settings.PLATFORM_URL}/channels/{channel['channel_id']}"
            result.append({
                'channel_name': channel['channel_name'],
                'channel_url': channel_url,
                'notification_count': channel['notification_count']
            })

        print(f"📊 [TOP_CHANNELS] Found {len(result)} channels with notifications (top 5)")
        return result
