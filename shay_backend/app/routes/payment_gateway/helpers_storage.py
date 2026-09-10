"""
Per-channel storage total aggregation.

Extracted from helpers.py (Raven style compliance, wave B). Used by
subscription_validation.py for both marketplace (vs
MARKETPLACE_STORAGE_LIMIT_MB) and SaaS (vs plan storage limit) checks.
"""

from typing import Any

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.attachment import Attachment
from app.models.email_attachment import EmailAttachment
from app.models.datasource import Datasource


async def _get_channel_storage_total(db: AsyncSession, channel_id: Any) -> int:
    """
    Return total storage in bytes for a channel: Attachment + EmailAttachment + Datasource file_size.
    Used for both marketplace (vs MARKETPLACE_STORAGE_LIMIT_MB) and SaaS (vs plan storage limit).
    """
    attachment_size_result = await db.execute(
        select(func.coalesce(func.sum(Attachment.file_size), 0)).where(
            Attachment.channel_id == channel_id
        )
    )
    attachment_size = attachment_size_result.scalar() or 0
    email_attachment_size_result = await db.execute(
        select(func.coalesce(func.sum(EmailAttachment.file_size), 0)).where(
            EmailAttachment.channel_id == channel_id
        )
    )
    email_attachment_size = email_attachment_size_result.scalar() or 0
    datasource_size_result = await db.execute(
        select(func.coalesce(func.sum(Datasource.file_size), 0)).where(
            Datasource.channel_id == channel_id
        )
    )
    datasource_size = datasource_size_result.scalar() or 0
    return int(attachment_size) + int(email_attachment_size) + int(datasource_size)
