"""
Background-task driver for the "approval reassigned" case.

Looks up the participants and eligible channel members, then sends
each one the reassignment email via notifications_reassigned_send.py.
"""

from uuid import UUID

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.channel import Channel
from app.models.user import User
from .notifications_shared import get_channel_members_with_approval_notifications_enabled
from .notifications_reassigned_send import send_approval_reassignment_notification_email


async def process_approval_reassignment_notifications(
    reassigner_id: str,
    reassigned_approver_id: str,
    channel_id: str,
    redirect_url: str,
    notification_settings_url: str
) -> None:
    """
    Process approval reassignment notifications for channel members.
    This function creates its own database session for background processing.

    Args:
        reassigner_id: UUID string of the user who reassigned the approval
        reassigned_approver_id: UUID string of the user reassigned to approve
        channel_id: UUID string of the channel where approval was reassigned
        redirect_url: Pre-constructed URL to redirect to view the approval
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

            # Get reassigned approver
            approver_stmt = select(User).where(User.id == UUID(reassigned_approver_id))
            approver_result = await db.execute(approver_stmt)
            reassigned_approver = approver_result.scalar_one_or_none()

            if not reassigned_approver:
                print(f"⚠️ Reassigned approver not found: {reassigned_approver_id}")
                return

            # Get channel
            channel_stmt = select(Channel).where(Channel.id == UUID(channel_id))
            channel_result = await db.execute(channel_stmt)
            channel = channel_result.scalar_one_or_none()

            if not channel:
                print(f"⚠️ Channel not found: {channel_id}")
                return

            # Get channel members with approval notifications enabled
            enabled_members = await get_channel_members_with_approval_notifications_enabled(
                channel.id,
                reassigner.id,
                db
            )

            if not enabled_members:
                print(f"ℹ️ No channel members with approval notifications enabled for channel {channel_id}")
                return

            # Send notification to each enabled member with pre-constructed URLs
            for member in enabled_members:
                await send_approval_reassignment_notification_email(
                    member,
                    reassigner,
                    reassigned_approver,
                    channel,
                    redirect_url,
                    notification_settings_url,
                    db
                )

        except Exception as e:
            print(f"❌ Error processing approval reassignment notifications: {e}")
            import traceback
            print(f"📋 Error traceback: {traceback.format_exc()}")
