"""
Channel-type/provider resolution, split out of channel_metrics.py during the
Raven style-compliance line-count pass (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, wave B3) — channel_metrics.py
itself needed to come in under 150 lines after being extracted as a shared
helper in wave B2.
"""

from typing import Any, Optional, Tuple

from sqlalchemy import and_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_account import AppAccount


async def resolve_channel_type_and_provider(db: AsyncSession, channel: Any) -> Tuple[Optional[str], Optional[str]]:
    """Resolve channel_type from the DB column and, for email/message
    channels, the connected provider."""
    if isinstance(channel.channel_type, str):
        channel_type = channel.channel_type
    elif channel.channel_type is not None:
        channel_type = str(channel.channel_type)
    else:
        channel_type = None

    provider = None
    if channel_type and channel_type.lower() == "email":
        email_app_account_query = select(AppAccount).where(
            and_(
                AppAccount.channel_id == channel.id,
                AppAccount.api_key == "email",
                AppAccount.is_active == True,
            )
        ).limit(1)
        email_app_account = (await db.execute(email_app_account_query)).scalar_one_or_none()
        if email_app_account and email_app_account.connection_settings:
            provider = (
                email_app_account.connection_settings.get("provider")
                if isinstance(email_app_account.connection_settings, dict)
                else None
            )
    elif channel_type and channel_type.lower() == "message":
        message_sync_query = text(
            """
            SELECT provider
            FROM gg_message_sync
            WHERE workspace_id = :workspace_id
            AND channel_id = :channel_id
            LIMIT 1
            """
        )
        message_sync_row = (
            await db.execute(
                message_sync_query,
                {"workspace_id": str(channel.workspace_id), "channel_id": str(channel.id)},
            )
        ).fetchone()
        if message_sync_row:
            provider = message_sync_row[0]

    return channel_type, provider
