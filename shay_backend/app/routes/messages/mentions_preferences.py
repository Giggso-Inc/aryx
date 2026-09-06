"""
Mention-notification preference check.

Split out of the former app/routes/messages/mentions.py — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5 / wave B2.
"""

from uuid import UUID

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.realtime_notification import RealtimeNotification


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
