"""
POST /zoho/subscriptions/cancel   cancel_subscription_new
(mounted at /api/v1/payment-gateway)

Split from a single subscription_cancel.py that also held
reactivate_zoho_subscription (now in subscription_reactivate.py) — the two
are similar in shape but independent Zoho-call-then-local-sync flows.
"""

from datetime import datetime

from fastapi import APIRouter, HTTPException, status, Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.subscription import Subscription
from app.schemas.common import SuccessResponse, SubscriptionCancelRequest
from app.services.zoho_service import get_zoho_service

import logging

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/zoho/subscriptions/cancel", response_model=SuccessResponse[dict])
async def cancel_subscription_new(
    subscription_request: SubscriptionCancelRequest,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> SuccessResponse[dict]:
    """
    Cancel a subscription in Zoho and update local database.

    This endpoint cancels a subscription in Zoho and updates the local database
    subscription status accordingly.

    Note: If you may need to reactivate later, use cancelAtEnd: true (non_renewing).
    Immediate cancel (cancelAtEnd: false) terminates the subscription in Zoho; some
    Zoho setups do not allow reactivating immediately-cancelled subscriptions.

    Reference: https://www.zoho.com/billing/api/v1/subscription/#cancel-a-subscription
    """
    try:
        # Get current user for authentication (matches Java: getResourceMainFromAuthHeader)
        user = await get_current_user_required(request)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unauthorized"
            )

        subscription_id = subscription_request.subscriptionId
        cancel_at_end = subscription_request.cancelAtEnd
        platform_name = subscription_request.platform_name

        # Get appropriate Zoho service instance
        zoho_service_instance = get_zoho_service(platform_name)

        # Call Zoho service to cancel subscription
        try:
            zoho_response = await zoho_service_instance.cancel_subscription(
                subscription_id=subscription_id,
                cancel_at_end=cancel_at_end
            )

            if not zoho_response:
                return SuccessResponse(
                    success=False,
                    data=None,
                    message="Failed to cancel subscription",
                    code=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

            # Update local database subscription
            # Find subscription by zoho_subscription_id - get the latest one only
            subscription_result = await db.execute(
                select(Subscription)
                .where(Subscription.zoho_subscription_id == subscription_id)
                .order_by(Subscription.created_at.desc())
                .limit(1)
            )
            subscription = subscription_result.scalar_one_or_none()

            if subscription:
                # Extract subscription data from Zoho response
                subscription_data = zoho_response.get('subscription', {})

                # Prepare update values
                update_values = {
                    "status": "inactive",
                    "subscription_status": "inactive",
                    "updated_at": datetime.utcnow()
                }

                # Update current_term_ends_at if available in Zoho response
                current_term_ends_at = subscription_data.get('current_term_ends_at')
                if current_term_ends_at:
                    try:
                        # Parse the date string (format: "2016-06-05")
                        # Zoho returns date in YYYY-MM-DD format
                        end_date = datetime.strptime(current_term_ends_at, "%Y-%m-%d")
                        update_values["current_period_end"] = end_date
                        logger.info(f"🔄 Updating current_period_end to: {end_date}")
                    except Exception as date_error:
                        logger.warning(f"Could not parse current_term_ends_at: {date_error}")

                # Update zoho_cancel_at_period_end based on cancel_at_end flag
                # If cancel_at_end is True, subscription will cancel at period end
                # If cancel_at_end is False, subscription is cancelled immediately
                update_values["zoho_cancel_at_period_end"] = cancel_at_end if cancel_at_end is not None else False

                # Update subscription in database
                await db.execute(
                    update(Subscription)
                    .where(Subscription.id == subscription.id)
                    .values(**update_values)
                )

                await db.commit()
                logger.info(f"✅ Local database updated for subscription {subscription_id} - status set to inactive")
            else:
                logger.warning(f"⚠️ Subscription with zoho_subscription_id {subscription_id} not found in local database")

            return SuccessResponse(
                success=True,
                data=zoho_response,
                message="Subscription cancelled successfully",
                code=status.HTTP_200_OK
            )

        except Exception as zoho_error:
            logger.error(f"Zoho API error: {zoho_error}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to cancel subscription: {str(zoho_error)}"
            )

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Exception at cancel subscription: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}"
        )
