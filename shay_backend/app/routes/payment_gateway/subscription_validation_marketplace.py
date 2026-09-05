"""
Marketplace-mode limit validation for subscription_validation.py
(POST /zoho/subscriptions/validation/{user_id}).

When settings.IS_MARKETPLACE is true, no plan or subscription is checked;
limits come from env (CHANNEL_COUNT, MESSAGE_COUNT,
MARKETPLACE_STORAGE_LIMIT_MB) instead of plan features. Split out of the
single ~185-line handler (Raven style compliance, wave B); see
subscription_validation_plan.py for the non-marketplace counterpart, which
performs the same three checks against a different limit source.
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.config import settings
from app.models.channel import Channel
from app.models.message import Message
from app.schemas.common import SuccessResponse

from fastapi import status

from .helpers_storage import _get_channel_storage_total


async def validate_marketplace_limits(db: AsyncSession, company_id, channel_id) -> SuccessResponse:
    """Validate channel/message/attachment limits using env-configured
    marketplace limits. Returns the final SuccessResponse for the request."""
    response_data = {}

    channel_limit = settings.CHANNEL_COUNT
    if channel_limit <= 0:
        response_data["canCreateChannel"] = False
    else:
        count_result = await db.execute(select(func.count()).select_from(Channel).where(Channel.company_id == company_id))
        current_count = count_result.scalar() or 0
        response_data["canCreateChannel"] = current_count < channel_limit

    if channel_id:
        ch_result = await db.execute(select(Channel).where(Channel.id == channel_id))
        ch = ch_result.scalar_one_or_none()
        if not ch or str(ch.company_id) != str(company_id):
            response_data["canCreateMessage"] = False
            response_data["canCreateAttachment"] = False
        else:
            msg_limit = settings.MESSAGE_COUNT
            if msg_limit <= 0:
                response_data["canCreateMessage"] = False
            else:
                msg_count_result = await db.execute(
                    select(func.count()).select_from(Message).where(
                        Message.channel_id == channel_id,
                        Message.message_type.in_(["user", "email"]),
                    )
                )
                current_msg_count = msg_count_result.scalar() or 0
                response_data["canCreateMessage"] = current_msg_count < msg_limit
            # Marketplace: 200MB per channel (attachments + datasources)
            limit_bytes = settings.MARKETPLACE_STORAGE_LIMIT_MB * 1024 * 1024
            total_size = await _get_channel_storage_total(db, channel_id)
            response_data["canCreateAttachment"] = total_size < limit_bytes
    else:
        response_data["canCreateMessage"] = None
        response_data["canCreateAttachment"] = None

    return SuccessResponse(success=True, data=response_data, message="OK", code=status.HTTP_200_OK)
