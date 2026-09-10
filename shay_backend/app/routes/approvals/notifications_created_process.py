"""
Background-task driver for the "approval created" case.

Looks up the participants and eligible channel members, then sends
each one the created-approval email via notifications_created_send.py.
"""

from uuid import UUID

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.channel import Channel
from app.models.user import User
from .notifications_shared import get_channel_members_with_approval_notifications_enabled
from .notifications_created_send import send_approval_notification_email


async def process_approval_notifications(
    approval_creator_id: str,
    approver_user_id: str,
    channel_id: str,
    redirect_url: str,
    notification_settings_url: str
) -> None:
    """
    Process approval notifications for channel members.
    This function creates its own database session for background processing.

    Args:
        approval_creator_id: UUID string of the user who created the approval
        approver_user_id: UUID string of the user who needs to approve
        channel_id: UUID string of the channel where approval was created
        redirect_url: Pre-constructed URL to redirect to view the approval
        notification_settings_url: Pre-constructed URL to notification settings page
    """
    # Create new session for background task
    async with AsyncSessionLocal() as db:
        try:
            # Get approval creator
            creator_stmt = select(User).where(User.id == UUID(approval_creator_id))
            creator_result = await db.execute(creator_stmt)
            approval_creator = creator_result.scalar_one_or_none()

            if not approval_creator:
                print(f"⚠️ Approval creator not found: {approval_creator_id}")
                return

            # Get approver user
            approver_stmt = select(User).where(User.id == UUID(approver_user_id))
            approver_result = await db.execute(approver_stmt)
            approver_user = approver_result.scalar_one_or_none()

            if not approver_user:
                print(f"⚠️ Approver user not found: {approver_user_id}")
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
                approval_creator.id,
                db
            )

            if not enabled_members:
                print(f"ℹ️ No channel members with approval notifications enabled for channel {channel_id}")
                return

            # Send notification to each enabled member with pre-constructed URLs
            for member in enabled_members:
                await send_approval_notification_email(
                    member,
                    approval_creator,
                    approver_user,
                    channel,
                    redirect_url,
                    notification_settings_url,
                    db
                )

        except Exception as e:
            print(f"❌ Error processing approval notifications: {e}")
            import traceback
            print(f"📋 Error traceback: {traceback.format_exc()}")
