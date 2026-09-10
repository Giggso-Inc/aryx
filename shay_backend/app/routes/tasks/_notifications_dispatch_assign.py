"""
process_task_assignment_notifications: background-task entry point
scheduled via FastAPI's BackgroundTasks from create.py. Split out of the
former notifications_dispatch.py (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md) to keep every resulting
file under the 150-line target; re-exported (unchanged import path) from
notifications_dispatch.py.
"""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.user import User
from app.models.channel import Channel

from ._notifications_membership import get_channel_members_with_task_notifications_enabled
from .notifications_email import send_task_assignment_notification_email


async def process_task_assignment_notifications(
    task_creator_id: str,
    assigned_user_id: str,
    channel_id: str,
    task_title: str,
    redirect_url: str,
    notification_settings_url: str
) -> None:
    """
    Process task assignment notifications for channel members.
    This function creates its own database session for background processing.

    Args:
        task_creator_id: UUID string of the user who created the task
        assigned_user_id: UUID string of the user assigned to the task
        channel_id: UUID string of the channel where task was created
        task_title: Title of the task
        redirect_url: Pre-constructed URL to redirect to view the task
        notification_settings_url: Pre-constructed URL to notification settings page
    """
    # Create new session for background task
    async with AsyncSessionLocal() as db:
        try:
            # Get task creator
            creator_stmt = select(User).where(User.id == UUID(task_creator_id))
            creator_result = await db.execute(creator_stmt)
            task_creator = creator_result.scalar_one_or_none()

            if not task_creator:
                print(f"⚠️ Task creator not found: {task_creator_id}")
                return

            # Get assigned user
            assigned_stmt = select(User).where(User.id == UUID(assigned_user_id))
            assigned_result = await db.execute(assigned_stmt)
            assigned_user = assigned_result.scalar_one_or_none()

            if not assigned_user:
                print(f"⚠️ Assigned user not found: {assigned_user_id}")
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
                task_creator.id,
                db
            )

            if not enabled_members:
                print(f"ℹ️ No channel members with task notifications enabled for channel {channel_id}")
                return

            # Send notification to each enabled member with pre-constructed URLs
            for member in enabled_members:
                await send_task_assignment_notification_email(
                    member,
                    task_creator,
                    assigned_user,
                    channel,
                    task_title,
                    redirect_url,
                    notification_settings_url,
                    db
                )

        except Exception as e:
            print(f"❌ Error processing task assignment notifications: {e}")
            import traceback
            print(f"📋 Error traceback: {traceback.format_exc()}")
