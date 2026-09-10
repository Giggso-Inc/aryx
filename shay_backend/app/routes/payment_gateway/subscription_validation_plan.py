"""
Plan-feature-based limit validation for subscription_validation.py
(POST /zoho/subscriptions/validation/{user_id}).

When settings.IS_MARKETPLACE is false, requires an active subscription and
plan; channel, message, and attachment limits are read from plan features.
Split out of the single ~185-line handler (Raven style compliance, wave B);
see subscription_validation_marketplace.py for the marketplace counterpart,
which performs the same three checks against a different limit source.
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.models.channel import Channel
from app.models.message import Message
from app.models.subscription import Subscription
from app.models.subscription_plan import SubscriptionPlan
from app.schemas.common import SuccessResponse

from fastapi import status

from .helpers_feature_parsing import (
    _parse_channel_limit_from_features,
    _parse_message_limit_from_features,
    _parse_storage_limit_from_features,
)
from .helpers_storage import _get_channel_storage_total


async def validate_plan_limits(db: AsyncSession, company_id, channel_id) -> SuccessResponse:
    """Validate channel/message/attachment limits against the company's
    active subscription's plan features. Returns the final SuccessResponse
    for the request (including the "no subscription"/"plan not found"
    early-exit variants)."""
    sub_result = await db.execute(
        select(Subscription)
        .where(Subscription.company_id == company_id, Subscription.status == "active")
        .order_by(Subscription.created_at.desc())
        .limit(1)
    )
    subscription = sub_result.scalar_one_or_none()
    if not subscription:
        response_data = {
            "canCreateChannel": False,
            "canCreateMessage": False if channel_id else None,
            "canCreateAttachment": False if channel_id else None,
        }
        return SuccessResponse(success=True, data=response_data, message="No active subscription for company", code=status.HTTP_200_OK)

    plan_result = await db.execute(select(SubscriptionPlan).where(SubscriptionPlan.id == subscription.plan_id))
    plan = plan_result.scalar_one_or_none()
    if not plan:
        response_data = {
            "canCreateChannel": False,
            "canCreateMessage": False if channel_id else None,
            "canCreateAttachment": False if channel_id else None,
        }
        return SuccessResponse(success=True, data=response_data, message="Plan not found", code=status.HTTP_200_OK)

    response_data = {}

    # --- 1. Channel validation (always) ---
    channel_limit = _parse_channel_limit_from_features(plan.features)
    if channel_limit == -1:
        response_data["canCreateChannel"] = True
    elif channel_limit <= 0:
        response_data["canCreateChannel"] = False
    else:
        count_result = await db.execute(select(func.count()).select_from(Channel).where(Channel.company_id == company_id))
        current_count = count_result.scalar() or 0
        response_data["canCreateChannel"] = current_count < channel_limit

    # --- 2. Message validation (if channel_id provided) ---
    if channel_id:
        ch_result = await db.execute(select(Channel).where(Channel.id == channel_id))
        ch = ch_result.scalar_one_or_none()
        if not ch or str(ch.company_id) != str(company_id):
            response_data["canCreateMessage"] = False
            response_data["canCreateAttachment"] = False
        else:
            msg_limit = _parse_message_limit_from_features(plan.features)
            if msg_limit == -1:
                response_data["canCreateMessage"] = True
            elif msg_limit <= 0:
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

            storage_limit_bytes = _parse_storage_limit_from_features(plan.features)
            if storage_limit_bytes == -1:
                response_data["canCreateAttachment"] = True
            elif storage_limit_bytes <= 0:
                response_data["canCreateAttachment"] = False
            else:
                # Total storage: attachments + email attachments + datasources
                total_size = await _get_channel_storage_total(db, channel_id)
                response_data["canCreateAttachment"] = total_size < storage_limit_bytes
    else:
        response_data["canCreateMessage"] = None
        response_data["canCreateAttachment"] = None

    return SuccessResponse(success=True, data=response_data, message="OK", code=status.HTTP_200_OK)
