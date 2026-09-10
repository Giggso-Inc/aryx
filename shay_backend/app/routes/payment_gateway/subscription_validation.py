"""
POST /zoho/subscriptions/validation/{user_id}   subscription_validation
(mounted at /api/v1/payment-gateway)

Thin orchestrator: validates the path/body UUIDs, resolves the user and
company, then delegates the actual channel/message/attachment limit checks
to whichever sibling module matches the marketplace setting:
  - subscription_validation_marketplace.py -> IS_MARKETPLACE True (env limits)
  - subscription_validation_plan.py        -> IS_MARKETPLACE False (plan features)
Split from a single ~185-line handler (Raven style compliance, wave B); the
two branches perform the same three checks against different limit sources,
so each keeps its own file rather than being fragmented further.
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, status, Request, Depends, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.config import settings
from app.models.user import User
from app.schemas.common import SuccessResponse, SubscriptionValidationRequest

from .helpers import _is_valid_uuid
from .subscription_validation_marketplace import validate_marketplace_limits
from .subscription_validation_plan import validate_plan_limits

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

        if not company_id:
            response_data = {
                "canCreateChannel": False,
                "canCreateMessage": False if channel_id else None,
                "canCreateAttachment": False if channel_id else None,
            }
            return SuccessResponse(success=True, data=response_data, message="User has no company", code=status.HTTP_200_OK)

        # Marketplace: do not check subscription or plan; use only env limits.
        # Non-marketplace: require active subscription and plan; use plan features.
        if settings.IS_MARKETPLACE:
            return await validate_marketplace_limits(db, company_id, channel_id)
        return await validate_plan_limits(db, company_id, channel_id)

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Exception at subscription validation: %s", e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Internal server error: {str(e)}")
