"""
@mention notification background-task orchestrator, run from create_message.

Split out of the original app/routes/messages.py (2,513 lines) — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5.

Wave B2 follow-up: the original Phase-5 file bundled parse/lookup,
preference-check, and email-send alongside this orchestrator behind a
"stated exception" (shared db-session threading). Re-examined: each step
only needs the session as a plain argument, not shared mutable state, so
they split cleanly into mentions_parsing.py, mentions_preferences.py, and
mentions_email.py. This file now only sequences those steps.
"""

from uuid import UUID

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.user import User
from app.models.channel import Channel

from .mentions_parsing import parse_mentions_from_content, get_users_by_mentions
from .mentions_preferences import should_send_mention_notification
from .mentions_email import send_mention_notification_email

__all__ = [
    "parse_mentions_from_content",
    "get_users_by_mentions",
    "should_send_mention_notification",
    "send_mention_notification_email",
    "process_mention_notifications",
]


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
