"""
@mention parsing and mention-notification email pipeline, run as a
background task from create_message.

Split out of the original app/routes/messages.py (2,513 lines) — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5.

Stated exception: parse/lookup/preference-check/send are kept in this one
file rather than split further — process_mention_notifications is the
single background-task entry point that threads a database session through
all four steps in sequence, so separating them would mean passing that
session and half-built state across module boundaries for no readability
gain.
"""

import re
from datetime import datetime
from typing import List, Set
from uuid import UUID

from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.config import settings
from app.models.user import User
from app.models.channel import Channel
from app.models.realtime_notification import RealtimeNotification
from app.services.email_service import email_service


def parse_mentions_from_content(content: str) -> Set[str]:
    """
    Parse mentions from message content.
    Extracts @username patterns from the content.
    Mentions use user names, not emails.
    Handles formats like:
    - @username

    Args:
        content: Message content string

    Returns:
        Set of mentioned user names (without @ symbol)
    """
    if not content:
        return set()

    # Pattern to match @username
    # Matches @ followed by alphanumeric characters, dots, hyphens, underscores
    # We'll extract each @mention separately
    mention_pattern = r'@([a-zA-Z0-9._-]+)'
    mentions = re.findall(mention_pattern, content)

    # Return unique mentions as a set
    return set(mentions)


async def get_users_by_mentions(mentions: Set[str], db: AsyncSession) -> List[User]:
    """
    Find users by their name from mentions.
    Mentions in content use user names, not emails.

    Args:
        mentions: Set of mention identifiers (user names)
        db: Database session

    Returns:
        List of User objects that match the mentions (unique users only)
    """
    if not mentions:
        return []

    found_user_ids = set()  # Track found user IDs to avoid duplicates
    users = []

    for mention in mentions:
        # Find users by name (case-insensitive matching)
        # Try exact match first
        stmt = select(User).where(func.lower(User.name) == func.lower(mention))
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()

        if user and user.id not in found_user_ids:
            users.append(user)
            found_user_ids.add(user.id)
            continue

        # If exact match not found, try partial match (contains)
        stmt = select(User).where(func.lower(User.name).contains(func.lower(mention)))
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()

        if user and user.id not in found_user_ids:
            users.append(user)
            found_user_ids.add(user.id)

    return users


async def should_send_mention_notification(
    mentioned_user: User,
    channel_id: UUID,
    db: AsyncSession
) -> bool:
    """
    Check if mention notification should be sent to a user.

    Logic:
    1. If no data exists in gg_realtime_notification, send notification (default: mention enabled)
    2. If data exists:
       - Check is_notifications_enabled - if false, don't send
       - If true, check is_mention_enabled - if false, don't send
       - If both true, send notification

    Args:
        mentioned_user: User who was mentioned
        channel_id: Channel ID where the mention occurred
        db: Database session

    Returns:
        bool: True if notification should be sent, False otherwise
    """
    # Check if notification preferences exist for this user and channel
    stmt = select(RealtimeNotification).where(
        and_(
            RealtimeNotification.user_id == mentioned_user.id,
            RealtimeNotification.channel_id == channel_id
        )
    )
    result = await db.execute(stmt)
    notification_pref = result.scalar_one_or_none()

    # If no data exists, send notification (default behavior - mention is enabled)
    if not notification_pref:
        return True

    # If data exists, check the flags
    # First check master switch
    if not notification_pref.is_notifications_enabled:
        return False

    # Then check mention-specific flag
    if not notification_pref.is_mention_enabled:
        return False

    # Both flags are true, send notification
    return True


async def send_mention_notification_email(
    mentioned_user: User,
    comment_author: User,
    channel: Channel,
    comment_content: str,
    redirect_url: str,
    notification_settings_url: str,
    db: AsyncSession
) -> bool:
    """
    Send mention notification email to the mentioned user.

    Args:
        mentioned_user: User who was mentioned
        comment_author: User who posted the comment
        channel: Channel where the mention occurred
        comment_content: The comment content
        redirect_url: URL to redirect to view the message/thread
        notification_settings_url: URL to notification settings page
        db: Database session

    Returns:
        bool: True if email sent successfully, False otherwise
    """
    try:
        # Load the mention notification template
        template = email_service._load_template('mention_notification.html')

        # Get platform name from config
        platform_name = settings.PLATFORM_NAME

        # Prepare template variables
        template_variables = {
            'user': comment_author.name or comment_author.email_id or 'Someone',
            'user_email': comment_author.email_id or '',
            'user_role': comment_author.role or 'user',
            'channel_name': channel.name or 'the channel',
            'comment': comment_content,
            'platform_name': platform_name,
            'redirect_url': redirect_url,
            'notification_settings_url': notification_settings_url,
            'current_year': datetime.now().year,
            'logo_html': email_service._get_embedded_logo_html(),
        }

        # Process template with variables
        processed_html = template.format(**template_variables)

        # Create email message (HTML only, no plain text)
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart

        msg = MIMEMultipart('alternative')
        msg['From'] = email_service.from_email
        msg['To'] = mentioned_user.email_id
        msg['Subject'] = f"{comment_author.name or 'Someone'} mentioned you in {channel.name or 'a channel'}"

        # Attach HTML version only (no plain text)
        msg.attach(MIMEText(processed_html, 'html'))

        # Send email
        result = email_service._send_email(msg)

        if result:
            print(f"✅ Mention notification email sent successfully to {mentioned_user.email_id}")
        else:
            print(f"❌ Failed to send mention notification email to {mentioned_user.email_id}")

        return result

    except Exception as e:
        print(f"❌ Error sending mention notification email to {mentioned_user.email_id}: {e}")
        import traceback
        print(f"📋 Error traceback: {traceback.format_exc()}")
        return False


async def process_mention_notifications(
    content: str,
    comment_author_id: str,
    channel_id: str,
    redirect_url: str,
    notification_settings_url: str
) -> None:
    """
    Process mention notifications for a message.
    Parses mentions, checks notification preferences, and sends emails.
    This function creates its own database session for background processing.

    Args:
        content: Message content
        comment_author_id: UUID string of the user who posted the comment
        channel_id: UUID string of the channel where the message was posted
        redirect_url: Pre-constructed URL to redirect to view the message/thread
        notification_settings_url: Pre-constructed URL to notification settings page
    """
    # Create new session for background task
    async with AsyncSessionLocal() as db:
        try:
            # Get comment author
            author_stmt = select(User).where(User.id == UUID(comment_author_id))
            author_result = await db.execute(author_stmt)
            comment_author = author_result.scalar_one_or_none()

            if not comment_author:
                print(f"⚠️ Comment author not found: {comment_author_id}")
                return

            # Get channel
            channel_stmt = select(Channel).where(Channel.id == UUID(channel_id))
            channel_result = await db.execute(channel_stmt)
            channel = channel_result.scalar_one_or_none()

            if not channel:
                print(f"⚠️ Channel not found: {channel_id}")
                return

            # Parse mentions from content
            mentions = parse_mentions_from_content(content)

            if not mentions:
                return  # No mentions found

            # Get users by mentions
            mentioned_users = await get_users_by_mentions(mentions, db)

            if not mentioned_users:
                return  # No users found for mentions

            # Process each mentioned user
            for mentioned_user in mentioned_users:
                # Skip if user mentions themselves
                if mentioned_user.id == comment_author.id:
                    continue

                # Check if notification should be sent
                should_send = await should_send_mention_notification(
                    mentioned_user,
                    channel.id,
                    db
                )

                if should_send:
                    # Send notification email with pre-constructed URLs
                    await send_mention_notification_email(
                        mentioned_user,
                        comment_author,
                        channel,
                        content,
                        redirect_url,
                        notification_settings_url,
                        db
                    )

        except Exception as e:
            print(f"❌ Error processing mention notifications: {e}")
            import traceback
            print(f"📋 Error traceback: {traceback.format_exc()}")
