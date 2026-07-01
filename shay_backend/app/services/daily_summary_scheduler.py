"""
Daily Summary Email Scheduler Service

This module provides a scheduler service that sends daily summary emails
to users based on their notification routine settings.

Author: AI Assistant
Date: 2025-01-XX
Version: 1.0.0
"""

import uuid
from datetime import datetime, timedelta, timezone


def ensure_timezone_aware(dt: datetime) -> datetime:
    """
    Ensure a datetime is timezone-aware (UTC).
    If the datetime is naive, assume it's UTC and add timezone info.
    
    Args:
        dt: Datetime object (may be naive or aware)
        
    Returns:
        Timezone-aware datetime in UTC
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        # If naive, assume it's UTC and make it aware
        return dt.replace(tzinfo=timezone.utc)
    # If already aware, convert to UTC
    return dt.astimezone(timezone.utc)


def datetime_for_db(dt: datetime) -> datetime:
    """
    Convert a datetime to naive UTC for database queries.
    Database DateTime columns are naive, so we need to convert timezone-aware
    datetimes to naive UTC before using them in queries.
    
    Args:
        dt: Datetime object (may be naive or aware)
        
    Returns:
        Naive datetime in UTC (for database queries)
    """
    if dt is None:
        return None
    # First ensure it's timezone-aware
    aware_dt = ensure_timezone_aware(dt)
    # Then convert to naive UTC (remove timezone info)
    return aware_dt.replace(tzinfo=None)
from typing import List, Dict, Optional, Any
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_, desc
from sqlalchemy.orm import selectinload

from app.core.database import AsyncSessionLocal
from app.models.email_notify_settings import EmailNotifySettings
from app.models.user import User
from app.models.message import Message
from app.models.task import Task
from app.models.approval import Approval
from app.models.channel import Channel
from app.models.channel_member import ChannelMember
from app.services.email_service import email_service
from app.core.config import settings


class DailySummaryScheduler:
    """Scheduler service for sending daily summary emails"""
    
    def __init__(self):
        """Initialize the scheduler"""
        # Configure AsyncIOScheduler to work with FastAPI's event loop
        import asyncio
        try:
            # Try to get the current event loop
            loop = asyncio.get_event_loop()
        except RuntimeError:
            # If no event loop exists, create a new one
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        self.scheduler = AsyncIOScheduler(event_loop=loop)
        self.is_running = False
    
    def start(self):
        """Start the scheduler"""
        if not self.is_running:
            # Run every 15 minutes to check all routine intervals
            self.scheduler.add_job(
                self.process_daily_summaries,
                trigger=IntervalTrigger(minutes=15),
                id='daily_summary_emails',
                replace_existing=True,
                max_instances=1
            )
            self.scheduler.start()
            self.is_running = True
            print("✅ Daily summary email scheduler started (runs every 15 minutes)")
            
            # Log next run time for debugging
            job = self.scheduler.get_job('daily_summary_emails')
            if job:
                print(f"📅 Next scheduled run: {job.next_run_time}")
                print(f"📋 Job ID: {job.id}, Trigger: {job.trigger}")
            else:
                print("⚠️ Warning: Job not found after adding")
    
    def stop(self):
        """Stop the scheduler"""
        if self.is_running:
            self.scheduler.shutdown()
            self.is_running = False
            print("⏹️ Daily summary email scheduler stopped")
    
    async def process_daily_summaries(self):
        """
        Process and send daily summary emails for all users who need them.
        This function runs every 15 minutes and checks which users need emails
        based on their routine settings and last_email_notify_time.
        """
        try:
            current_time = datetime.now(timezone.utc)
            print(f"🔄 [SCHEDULER] ===== STARTING PROCESS ===== at {current_time}")
            print(f"🔄 [SCHEDULER] Scheduler is_running: {self.is_running}")
            
            # Get database session
            async with AsyncSessionLocal() as db:
                print(f"🔄 [SCHEDULER] Database session created")
                try:
                    # Get all users with enabled email notifications
                    users_to_notify = await self.get_users_to_notify(db)
                    
                    print(f"📧 [SCHEDULER] Found {len(users_to_notify)} users to notify")
                    
                    # Process each user
                    for user_settings in users_to_notify:
                        try:
                            await self.send_daily_summary_email(user_settings, db)
                        except Exception as e:
                            print(f"❌ Error sending email to user {user_settings.resource_id}: {e}")
                            continue
                    
                    print(f"✅ Finished processing daily summary emails")
                    
                except Exception as e:
                    print(f"❌ Error in process_daily_summaries: {e}")
                    import traceback
                    print(traceback.format_exc())
                    
        except Exception as e:
            print(f"❌ Error in process_daily_summaries: {e}")
            import traceback
            print(traceback.format_exc())
    
    async def get_users_to_notify(self, db: AsyncSession) -> List[EmailNotifySettings]:
        """
        Get list of users who need to receive daily summary emails.
        
        Criteria:
        - is_notification_enabled = 1
        - routine is set (not None)
        - Either last_email_notify_time is None OR
          (current_time - last_email_notify_time) >= routine minutes
        """
        now = datetime.now(timezone.utc)
        
        # Get all enabled notification settings
        stmt = select(EmailNotifySettings).where(
            EmailNotifySettings.is_notification_enabled == 1,
            EmailNotifySettings.routine.isnot(None)
        )
        result = await db.execute(stmt)
        all_settings = result.scalars().all()
        
        print(f"🔍 [SCHEDULER] Found {len(all_settings)} total users with notifications enabled")
        
        users_to_notify = []
        
        for setting in all_settings:
            # Check if user needs notification
            if setting.last_email_notify_time is None:
                # First time - last_email_notify_time is NULL, send email now
                print(f"🔍 [SCHEDULER] User {setting.resource_id}: First time (last_email_notify_time is NULL) - WILL NOTIFY")
                users_to_notify.append(setting)
            else:
                # Ensure timezone-aware datetime for comparison
                last_notify_time = ensure_timezone_aware(setting.last_email_notify_time)
                # Calculate time difference
                time_diff = now - last_notify_time
                routine_minutes = setting.routine
                
                # Check if enough time has passed
                if time_diff >= timedelta(minutes=routine_minutes):
                    print(f"🔍 [SCHEDULER] User {setting.resource_id}: Time passed ({time_diff.total_seconds()/60:.1f} mins) >= routine ({routine_minutes} mins) - WILL NOTIFY")
                    users_to_notify.append(setting)
                else:
                    remaining = timedelta(minutes=routine_minutes) - time_diff
                    print(f"🔍 [SCHEDULER] User {setting.resource_id}: Not yet time (need {routine_minutes} mins, have {time_diff.total_seconds()/60:.1f} mins, remaining {remaining.total_seconds()/60:.1f} mins)")
        
        return users_to_notify
    
    async def send_daily_summary_email(
        self,
        email_settings: EmailNotifySettings,
        db: AsyncSession
    ):
        """
        Send daily summary email to a user.
        
        Args:
            email_settings: EmailNotifySettings record for the user
            db: Database session
        """
        try:
            # Check if notifications are enabled before sending
            # Refresh the settings from database to get the latest value
            await db.refresh(email_settings)
            
            if email_settings.is_notification_enabled != 1:
                print(f"⚠️ Email notifications are disabled for user {email_settings.resource_id}, skipping daily summary")
                return
            
            # Check if at least one notification type is enabled
            has_enabled_type = (
                email_settings.mention_enabled == 1 or
                email_settings.post_enabled == 1 or
                email_settings.reply_enabled == 1 or
                email_settings.task_enabled == 1 or
                email_settings.approval_pending_enabled == 1 or
                email_settings.meeting_enabled == 1 or
                email_settings.blocker_enabled == 1 or
                email_settings.app_enabled == 1 or
                email_settings.chat_enabled == 1 or
                email_settings.friend_enabled == 1
            )
            
            if not has_enabled_type:
                print(f"⚠️ No notification types enabled for user {email_settings.resource_id}, skipping daily summary")
                return
            
            # Get user details
            user_stmt = select(User).where(User.id == email_settings.resource_id)
            user_result = await db.execute(user_stmt)
            user = user_result.scalar_one_or_none()
            
            if not user or not user.email_id:
                print(f"⚠️ User {email_settings.resource_id} not found or has no email")
                return
            
            # Collect notification counts based on enabled types
            notification_counts = await self.collect_notification_counts(
                user.id,
                email_settings,
                db
            )
            
            # Generate enabled cards HTML (only for enabled notification types with count > 0)
            enabled_cards = self.generate_enabled_cards(email_settings, notification_counts)
            
            # Get top 5 channels with notification counts
            top_channels = await self.get_top_channels(user.id, email_settings, db)
            
            # Only send email if there are either enabled cards (with count > 0) OR top channels
            if not enabled_cards and not top_channels:
                print(f"⚠️ No enabled notification types with data and no channels with notifications for user {user.email_id}, skipping daily summary")
                return
            
            # Generate email content (will handle case where enabled_cards is empty but channels exist)
            email_content = self.generate_email_content(
                user,
                email_settings,
                notification_counts,
                top_channels,
                enabled_cards
            )
            
            # Check if email content was generated
            if email_content is None or not email_content.strip():
                print(f"⚠️ No email content generated for user {user.email_id}, skipping send")
                return
            
            # Send email
            from email.mime.text import MIMEText
            from email.mime.multipart import MIMEMultipart
            
            msg = MIMEMultipart('alternative')
            msg['From'] = email_service.from_email
            msg['To'] = user.email_id
            msg['Subject'] = f"Daily Summary - {settings.PLATFORM_NAME}"
            
            # Attach HTML content
            msg.attach(MIMEText(email_content, 'html'))
            
            # Send email
            result = email_service._send_email(msg)
            
            if result:
                # Update last_email_notify_time
                email_settings.last_email_notify_time = datetime.now(timezone.utc)
                await db.commit()
                print(f"✅ Daily summary email sent to {user.email_id}")
            else:
                print(f"❌ Failed to send daily summary email to {user.email_id}")
                
        except Exception as e:
            print(f"❌ Error sending daily summary email: {e}")
            import traceback
            print(traceback.format_exc())
            raise
    
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
    
    def generate_email_content(
        self,
        user: User,
        email_settings: EmailNotifySettings,
        notification_counts: Dict[str, int],
        top_channels: List[Dict[str, Any]],
        enabled_cards: str
    ) -> str:
        """
        Generate email HTML content using the daily_summary_notification.html template.
        
        Args:
            user: User object
            email_settings: Email notification settings
            notification_counts: Dictionary of notification counts
            top_channels: List of top channels with notification counts
            enabled_cards: HTML string of enabled notification cards (may be empty)
            
        Returns:
            HTML content string
        """
        try:
            template = email_service._load_template('daily_summary_notification.html')
            user_name = user.name or user.email_id.split('@')[0] if user.email_id else 'User'
            platform_name = settings.PLATFORM_NAME
            domain_url = settings.PLATFORM_URL
            domain_name = settings.PLATFORM_URL.replace('http://', '').replace('https://', '').split('/')[0]
            notification_settings_url = f"{settings.PLATFORM_URL}/settings/notifications"
            current_year = datetime.now().year
            channels_rows = self.generate_channels_rows(top_channels)
            print(f"📊 [EMAIL] Generated channels rows for {len(top_channels)} top channels")

            email_content = template.format(
                platform_name=platform_name,
                user_name=user_name,
                domain_url=domain_url,
                domain_name=domain_name,
                notification_settings_url=notification_settings_url,
                enabled_cards=enabled_cards,
                groups_rows=channels_rows,
                current_year=current_year,
                logo_html=email_service._get_embedded_logo_html(),
            )
            
            return email_content
            
        except Exception as e:
            print(f"❌ Error generating email content: {e}")
            import traceback
            print(traceback.format_exc())
            raise
    
    def generate_enabled_cards(
        self,
        email_settings: EmailNotifySettings,
        notification_counts: Dict[str, int]
    ) -> str:
        """
        Generate HTML for enabled notification type cards.
        
        Args:
            email_settings: Email notification settings
            notification_counts: Dictionary of notification counts
            
        Returns:
            HTML string for cards
        """
        cards = []
        
        # Card HTML template
        card_template = """<td class="summary-card" style="display: table-cell; background-color: #F4F6FB; border: 1px solid #D9DEEB; border-radius: 14px; padding: 20px 16px; text-align: center; vertical-align: middle; box-sizing: border-box;">
            <div class="summary-card-number" style="font-size: 28px; font-weight: 700; margin: 0 0 6px 0; padding: 0; color: #0D1B5A; line-height: 1.2;">{count}</div>
            <div class="summary-card-label" style="font-size: 13px; font-weight: 600; margin: 0; padding: 0; color: #0B1430; line-height: 1.4;">{label}</div>
        </td>"""
        
        # Check each notification type and add card if enabled AND count > 0
        if email_settings.mention_enabled == 1:
            mention_count = notification_counts.get('mentions', 0)
            if mention_count > 0:
                cards.append(card_template.format(
                    count=mention_count,
                    label='Mentions'
                ))
        
        if email_settings.post_enabled == 1:
            post_count = notification_counts.get('posts', 0)
            if post_count > 0:
                cards.append(card_template.format(
                    count=post_count,
                    label='Posts'
                ))
            # Also add email conversations card when post is enabled (only if count > 0)
            email_conv_count = notification_counts.get('email_conversations', 0)
            if email_conv_count > 0:
                cards.append(card_template.format(
                    count=email_conv_count,
                    label='Email Conversations'
                ))
        
        if email_settings.reply_enabled == 1:
            reply_count = notification_counts.get('replies', 0)
            if reply_count > 0:
                cards.append(card_template.format(
                    count=reply_count,
                    label='Replies'
                ))
        
        if email_settings.task_enabled == 1:
            task_count = notification_counts.get('tasks', 0)
            if task_count > 0:
                cards.append(card_template.format(
                    count=task_count,
                    label='Tasks'
                ))
        
        if email_settings.approval_pending_enabled == 1:
            approval_count = notification_counts.get('approvals', 0)
            if approval_count > 0:
                cards.append(card_template.format(
                    count=approval_count,
                    label='Approvals'
                ))
        
        if email_settings.meeting_enabled == 1:
            meeting_count = notification_counts.get('meetings', 0)
            if meeting_count > 0:
                cards.append(card_template.format(
                    count=meeting_count,
                    label='Meetings'
                ))
        
        if email_settings.blocker_enabled == 1:
            blocker_count = notification_counts.get('blockers', 0)
            if blocker_count > 0:
                cards.append(card_template.format(
                    count=blocker_count,
                    label='Blockers'
                ))
        
        if email_settings.app_enabled == 1:
            app_count = notification_counts.get('apps', 0)
            if app_count > 0:
                cards.append(card_template.format(
                    count=app_count,
                    label='Apps'
                ))
        
        if email_settings.chat_enabled == 1:
            chat_count = notification_counts.get('chats', 0)
            if chat_count > 0:
                cards.append(card_template.format(
                    count=chat_count,
                    label='Chats'
                ))
        
        if email_settings.friend_enabled == 1:
            friend_count = notification_counts.get('friends', 0)
            if friend_count > 0:
                cards.append(card_template.format(
                    count=friend_count,
                    label='Friends'
                ))
        
        # If no cards, return empty string
        if not cards:
            return ""
        
        return '\n                '.join(cards)
    
    def generate_channels_rows(
        self,
        top_channels: List[Dict[str, Any]]
    ) -> str:
        """
        Generate HTML for top channels table rows with notification counts.
        
        Args:
            top_channels: List of channel dictionaries with notification counts
            
        Returns:
            HTML string for table rows
        """
        if not top_channels:
            return '<tr><td colspan="2" style="padding: 16px 18px; font-size: 14px; color: #0B1430; border-bottom: 1px solid #D9DEEB; text-align: center;">No channels with notifications found</td></tr>'
        
        rows = []
        row_template = """<tr>
            <td style="padding: 16px 18px; font-size: 14px; color: #0B1430; border-bottom: 1px solid #D9DEEB;">
                <a href="{channel_url}" class="group-name-link" style="color: #2D7DFF; text-decoration: none; font-weight: 600;">{channel_name}</a>
            </td>
            <td style="padding: 16px 18px; font-size: 14px; color: #0B1430; border-bottom: 1px solid #D9DEEB;">
                <span class="group-count" style="color: #0D1B5A; font-weight: 700;">{notification_count}</span>
            </td>
        </tr>"""
        
        for channel in top_channels:
            rows.append(row_template.format(
                channel_name=channel['channel_name'],
                channel_url=channel['channel_url'],
                notification_count=channel['notification_count']
            ))
        
        return '\n                    '.join(rows)


# Create singleton instance
daily_summary_scheduler = DailySummaryScheduler()
