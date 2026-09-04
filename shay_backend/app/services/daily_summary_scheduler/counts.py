"""
collect_notification_counts: aggregate per-notification-type counts across
all of a user's channels for the summary email.

Stated exception (well over the ~150-line-per-file target on its own): this
is one query-building pass over ten enabled-flag-gated count blocks that all
share the same time-window/channel-id setup computed once at the top of the
method. Splitting the individual count blocks into separate files would
duplicate that shared setup ten times over rather than isolate any
independently reusable concern. Same reasoning as
app/routes/tasks/crud.py's stated exception.
"""

from datetime import datetime, timedelta, timezone
from typing import Dict
import uuid

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.approval import Approval
from app.models.channel_member import ChannelMember
from app.models.email_notify_settings import EmailNotifySettings
from app.models.message import Message
from app.models.task import Task
from app.models.user import User

from .time_utils import datetime_for_db


class CountsMixin:
    """collect_notification_counts: per-user, all-channels aggregate counts."""

    async def collect_notification_counts(
        self,
        user_id: uuid.UUID,
        email_settings: EmailNotifySettings,
        db: AsyncSession
    ) -> Dict[str, int]:
        """
        Collect notification counts for enabled notification types.
        Time window is based on routine interval from current time.

        Args:
            user_id: User ID
            email_settings: Email notification settings
            db: Database session

        Returns:
            Dictionary with counts for each enabled notification type
        """
        now = datetime.now(timezone.utc)

        # Determine time window based on routine interval (in minutes)
        # routine values: 15, 30, 45, 60, 240, 480, 720, 1440 (minutes)
        if email_settings.routine:
            # Use routine interval from current time
            time_window_start = datetime_for_db(now - timedelta(minutes=email_settings.routine))
        else:
            # Default to 24 hours if no routine set
            time_window_start = datetime_for_db(now - timedelta(hours=24))

        counts = {}

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
            # User has no channels, return zero counts
            return {
                'mentions': 0,
                'posts': 0,
                'replies': 0,
                'tasks': 0,
                'approvals': 0,
                'meetings': 0,
                'blockers': 0,
                'apps': 0,
                'chats': 0,
                'friends': 0,
                'email_conversations': 0
            }

        # Get email channel IDs - channels that have messages with message_type='email'
        # This is a more reliable way to identify email channels
        email_channels_stmt = select(Message.channel_id).where(
            and_(
                Message.channel_id.in_(user_channel_ids),
                Message.message_type == 'email'
            )
        ).distinct()
        email_channels_result = await db.execute(email_channels_stmt)
        email_channel_ids = [row[0] for row in email_channels_result.all()]

        # Count mentions (messages that mention the user by name in content)
        if email_settings.mention_enabled == 1:
            if user_name:
                # Parse mentions from content - mentions use @username format
                # We need to check if content contains @user_name
                mentions_stmt = select(func.count(Message.id)).where(
                    and_(
                        Message.channel_id.in_(user_channel_ids),
                        Message.created_at >= time_window_start,
                        Message.message_type == 'user',
                        Message.content.ilike(f'%@{user_name}%')  # Check for @username in content
                    )
                )
                mentions_result = await db.execute(mentions_stmt)
                counts['mentions'] = mentions_result.scalar() or 0
            else:
                counts['mentions'] = 0

        # Count posts (user messages in channels) + email conversations if post is enabled
        if email_settings.post_enabled == 1:
            # Count regular posts (user messages, excluding user's own)
            posts_stmt = select(func.count(Message.id)).where(
                and_(
                    Message.channel_id.in_(user_channel_ids),
                    Message.created_at >= time_window_start,
                    Message.message_type == 'user',
                    Message.user_id != user_id  # Exclude user's own messages
                )
            )
            posts_result = await db.execute(posts_stmt)
            posts_count = posts_result.scalar() or 0

            # Count email conversations (message_type = 'email')
            email_conversations_stmt = select(func.count(Message.id)).where(
                and_(
                    Message.channel_id.in_(user_channel_ids),
                    Message.created_at >= time_window_start,
                    Message.message_type == 'email'
                )
            )
            email_conv_result = await db.execute(email_conversations_stmt)
            email_conv_count = email_conv_result.scalar() or 0

            # Posts count includes both regular posts and email conversations
            counts['posts'] = posts_count
            counts['email_conversations'] = email_conv_count
        else:
            counts['posts'] = 0
            counts['email_conversations'] = 0

        # Count replies (messages in email channels where replies were added)
        if email_settings.reply_enabled == 1:
            if email_channel_ids:
                # Get threads in email channels where user has messages
                user_email_threads_stmt = select(Message.thread_id).where(
                    and_(
                        Message.user_id == user_id,
                        Message.channel_id.in_(email_channel_ids)
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
                            Message.channel_id.in_(email_channel_ids)
                        )
                    )
                    replies_result = await db.execute(replies_stmt)
                    counts['replies'] = replies_result.scalar() or 0
                else:
                    counts['replies'] = 0
            else:
                counts['replies'] = 0

        # Count tasks (only tasks assigned to user, not by channel)
        if email_settings.task_enabled == 1:
            tasks_stmt = select(func.count(Task.id)).where(
                and_(
                    Task.assigned_to == user_id,  # Only check assigned_to column
                    Task.created_at >= time_window_start,
                    Task.status != 'Close'
                )
            )
            tasks_result = await db.execute(tasks_stmt)
            counts['tasks'] = tasks_result.scalar() or 0

        # Count approvals (approvals pending for user)
        if email_settings.approval_pending_enabled == 1:
            approvals_stmt = select(func.count(Approval.id)).where(
                and_(
                    Approval.approver_user_id == user_id,  # Check approver_user_id column
                    Approval.status == 'pending',
                    Approval.created_at >= time_window_start
                )
            )
            approvals_result = await db.execute(approvals_stmt)
            counts['approvals'] = approvals_result.scalar() or 0

        # Count blockers (tasks with blocker priority assigned to user)
        if email_settings.blocker_enabled == 1:
            blockers_stmt = select(func.count(Task.id)).where(
                and_(
                    Task.assigned_to == user_id,  # Only check assigned_to column
                    Task.priority == 'Blocker',
                    Task.status != 'Close',
                    Task.created_at >= time_window_start
                )
            )
            blockers_result = await db.execute(blockers_stmt)
            counts['blockers'] = blockers_result.scalar() or 0

        # For other types (meetings, apps, chats, friends), return 0 for now
        # These can be implemented based on your specific data models
        if email_settings.meeting_enabled == 1:
            counts['meetings'] = 0  # TODO: Implement meeting count

        if email_settings.app_enabled == 1:
            counts['apps'] = 0  # TODO: Implement app count

        if email_settings.chat_enabled == 1:
            counts['chats'] = 0  # TODO: Implement chat count

        if email_settings.friend_enabled == 1:
            counts['friends'] = 0  # TODO: Implement friend count

        return counts
