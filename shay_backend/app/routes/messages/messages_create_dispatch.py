"""
create_message sub-step: schedule background AI processing and mention
notifications for a newly created message.

Split out of app/routes/messages/messages_create.py — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, wave B2.

NOTE: tests/test_messages_characterization.py patches
`app.routes.messages.messages_create_dispatch.trigger_ai_processing`,
`...process_mention_notifications`, and
`...link_shortener_service.shorten` — keep these import names stable if
this file moves again.
"""

from fastapi import BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.channel import Channel
from app.models.message import Message, Thread
from app.services.link_shortener_service import link_shortener_service
from app.schemas.message import MessageCreate
from .mentions import process_mention_notifications
from .ai_processing import trigger_ai_processing


def schedule_ai_processing(
    background_tasks: BackgroundTasks,
    channel: Channel,
    thread: Thread,
    message: Message,
    message_data: MessageCreate,
) -> None:
    """Queue AI processing for the message if the channel/thread allow it."""
    if channel.ai_enabled and thread.ai_enabled and message_data.message_type == "user":
        background_tasks.add_task(trigger_ai_processing, message.id)


async def schedule_mention_notifications(
    db: AsyncSession,
    background_tasks: BackgroundTasks,
    user_id,
    channel: Channel,
    thread: Thread,
    message_data: MessageCreate,
) -> None:
    """Queue mention-notification processing for user messages."""
    if message_data.message_type != "user" or not message_data.content:
        return

    # Use the canonical frontend root for real-time notifications.
    platform_url = settings.PLATFORM_URL

    # Construct redirect URL to view the thread (shortened; store thread_id/channel_id for move-safe links)
    redirect_url = await link_shortener_service.shorten(
        f"{platform_url}/threads/{channel.id}", db,
        thread_id=thread.id, channel_id=channel.id, entity_type="mention",
    ) if platform_url else "#"
    # Construct notification settings URL (shortened; channel-level)
    notification_settings_url = await link_shortener_service.shorten(
        f"{platform_url}/threads/{channel.id}?openSettings=true&tab=notification", db,
        channel_id=channel.id, entity_type="channel",
    ) if platform_url else "#"

    # Process mentions in background to avoid blocking the response
    background_tasks.add_task(
        process_mention_notifications,
        message_data.content,
        str(user_id),  # The user ID who posted the comment
        str(channel.id),  # The channel ID where the message was posted
        redirect_url,  # Pre-constructed redirect URL
        notification_settings_url  # Pre-constructed notification settings URL
    )
