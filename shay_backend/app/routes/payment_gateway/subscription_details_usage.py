"""
Usage-statistics calculation for fetch_company_subscription_details: parses
plan feature limits, counts current message usage, and computes available
capacity. Extracted from subscription_details.py.
"""
import logging
from typing import Any, Dict

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.channel import Channel
from app.models.message import Message
from app.models.subscription_plan import SubscriptionPlan

from .helpers_feature_parsing import (
    _parse_channel_limit_from_features,
    _parse_message_limit_from_features,
    _parse_storage_limit_from_features,
)

logger = logging.getLogger(__name__)


async def _calculate_usage_statistics(
    db: AsyncSession,
    plan: SubscriptionPlan,
    channel_count: int,
    total_storage: int,
    company_id: Any,
) -> Dict[str, Any]:
    """Use the same parsing functions as the validation API for consistency."""
    try:
        channel_limit = _parse_channel_limit_from_features(plan.features)
        message_limit_per_channel = _parse_message_limit_from_features(plan.features)
        storage_limit_bytes_per_channel = _parse_storage_limit_from_features(plan.features)

        # Message and storage limits are per channel, so multiply by channel limit for total
        message_limit = message_limit_per_channel * channel_limit if channel_limit > 0 and message_limit_per_channel > 0 else 0
        storage_limit_bytes = storage_limit_bytes_per_channel * channel_limit if channel_limit > 0 and storage_limit_bytes_per_channel > 0 else 0

        current_channels = channel_count

        # Messages are directly linked to channels, and channels are linked to company
        message_count_result = await db.execute(
            select(func.count(Message.id)).where(
                Message.channel_id.in_(
                    select(Channel.id).where(Channel.company_id == company_id)
                )
            )
        )
        current_messages = message_count_result.scalar() or 0

        current_storage_bytes = total_storage

        channel_available = max(0, channel_limit - current_channels) if channel_limit > 0 else 0
        message_available = max(0, message_limit - current_messages) if message_limit > 0 else 0
        storage_available_bytes = max(0, storage_limit_bytes - current_storage_bytes) if storage_limit_bytes > 0 else 0

        return {
            "channelLimit": channel_limit,
            "messageLimit": message_limit,
            "StorageLimit": storage_limit_bytes,
            "channelavailable": channel_available,
            "messageavailable": message_available,
            "Storageavailable": storage_available_bytes
        }
    except Exception as usage_error:
        logger.warning(f"Error calculating usage statistics: {usage_error}")
        return {
            "channelLimit": 0,
            "messageLimit": 0,
            "StorageLimit": 0,
            "channelavailable": 0,
            "messageavailable": 0,
            "Storageavailable": 0
        }
