"""Shared redirect / notification-settings URL construction for approval
background notifications. Used by the reassign endpoint (create.py keeps its
own inline copy so tests patching app.routes.approvals.create.settings /
.link_shortener_service continue to resolve against that module directly).
"""

from app.core.config import settings
from app.services.link_shortener_service import link_shortener_service


async def build_notification_urls(channel_id, thread_id, db, entity_type: str = "approval") -> tuple:
    """Build the (redirect_url, notification_settings_url) pair for a
    background notification task, shortening both via link_shortener_service.

    Args:
        channel_id: The channel the notification links back to.
        thread_id: The thread the notification links back to.
        db: Database session, passed through to the link shortener.
        entity_type (str): Entity type recorded against the redirect link.

    Returns:
        tuple: (redirect_url, notification_settings_url) — "#" for both if
            PLATFORM_URL isn't configured.
    """
    platform_url = settings.PLATFORM_URL

    redirect_url = await link_shortener_service.shorten(
        f"{platform_url}/threads/{channel_id}/{thread_id}?openApproval=true", db,
        thread_id=thread_id, channel_id=channel_id, entity_type=entity_type,
    ) if platform_url else "#"

    notification_settings_url = await link_shortener_service.shorten(
        f"{platform_url}/threads/{channel_id}?openSettings=true&tab=notification", db,
        channel_id=channel_id, entity_type="channel",
    ) if platform_url else "#"

    return redirect_url, notification_settings_url
