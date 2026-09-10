"""
process_task_reassignment_notifications: background-task entry point
scheduled via FastAPI's BackgroundTasks from assign.py and update.py. Split
out of the former notifications_dispatch.py (Raven style-compliance pass,
see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md) to keep every
resulting file under the 150-line target; re-exported (unchanged import
path) from notifications_dispatch.py.
"""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.user import User
from app.models.channel import Channel

from ._notifications_membership import get_channel_members_with_task_notifications_enabled
from .notifications_email import send_task_reassignment_notification_email


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
