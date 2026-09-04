"""
POST /zoho/subscriptions/validation/{user_id}   subscription_validation
(mounted at /api/v1/payment-gateway)

Stated exception: kept as one ~185-line handler rather than split further —
the marketplace and non-marketplace branches each perform the same three
checks (channel/message/attachment) against different limit sources, and
splitting either branch out would duplicate the response-shape contract
(canCreateChannel/canCreateMessage/canCreateAttachment) across files rather
than isolating a reusable concern.
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, status, Request, Depends, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.database import get_db
from app.core.config import settings
from app.models.user import User
from app.models.channel import Channel
from app.models.message import Message
from app.models.subscription import Subscription
from app.models.subscription_plan import SubscriptionPlan
from app.schemas.common import SuccessResponse, SubscriptionValidationRequest

from .helpers import (
    _is_valid_uuid,
    _parse_channel_limit_from_features,
    _parse_message_limit_from_features,
    _parse_storage_limit_from_features,
    _get_channel_storage_total,
)

import logging

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/zoho/subscriptions/validation/{user_id}", response_model=SuccessResponse[dict])
async def subscription_validation(
        user_id: str,
        request: Request,
        db: AsyncSession = Depends(get_db),
        validation_request: Optional[SubscriptionValidationRequest] = Body(None),
) -> SuccessResponse[dict]:
    """
    Validate channel/message (and optionally attachment) limits in a single request.

    **channelId is optional.** For "can we create a channel?" only user_id is needed
    (no channel exists yet). Send channelId only when validating message (or attachment)
    count in an existing channel.

    When IS_MARKETPLACE is true: no plan or subscription is checked. Limits come from
    env (CHANNEL_COUNT, MESSAGE_COUNT, MARKETPLACE_STORAGE_LIMIT_MB). Channel, message,
    and attachment/datasource storage (200MB per channel by default) are validated.

    When IS_MARKETPLACE is false: requires active subscription and plan; channel,
    message, and attachment limits are read from plan features.

    Returns:
    - **canCreateChannel**: Can the company create more channels? (always checked; no channelId needed)
    - **canCreateMessage**: Can the company create more messages in this channel? (requires channelId in body)
    - **canCreateAttachment**: Can the company add more attachments/datasource in this channel? (requires channelId; in marketplace uses 200MB per channel limit)

    Request body: optional. If omitted, only canCreateChannel is validated.
    - channelId (optional): Omit for channel-only check. Provide a valid channel UUID when checking message/attachment limits.
    """
    try:
        # Validate UUIDs to avoid DB DataError when client sends placeholders (e.g. "string")
        if not _is_valid_uuid(user_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="user_id must be a valid UUID",
            )
        # Treat empty or placeholder values as "not provided" so channel-only check works without a real channelId
        channel_id_raw = validation_request.channelId if validation_request else None
        if channel_id_raw is None or (isinstance(channel_id_raw, str) and channel_id_raw.strip() == ""):
            channel_id = None
        elif isinstance(channel_id_raw, str) and channel_id_raw.strip().lower() in ("string", "uuid", "channel_id"):
            channel_id = None
        else:
            channel_id = channel_id_raw.strip() if isinstance(channel_id_raw, str) else channel_id_raw
            if not _is_valid_uuid(channel_id):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="channelId must be a valid UUID when provided",
                )

        user_result = await db.execute(select(User).where(User.id == user_id))
        user = user_result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        company_id = user.company_id

        # Initialize response data
        response_data = {}

        if not company_id:
            response_data = {
                "canCreateChannel": False,
                "canCreateMessage": False if channel_id else None,
                "canCreateAttachment": False if channel_id else None,
            }
            return SuccessResponse(success=True, data=response_data, message="User has no company", code=status.HTTP_200_OK)

        # Marketplace: do not check subscription or plan; use only env limits for channel and message
        if settings.IS_MARKETPLACE:
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

        # Non-marketplace: require active subscription and plan; use plan features for all validations
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

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Exception at subscription validation: %s", e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Internal server error: {str(e)}")
