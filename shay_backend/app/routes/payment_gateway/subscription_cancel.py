"""
Subscription cancel/reactivate endpoints (mounted at /api/v1/payment-gateway):
  POST /zoho/subscriptions/cancel       cancel_subscription_new
  POST /zoho/subscriptions/reactivate   reactivate_zoho_subscription

Grouped together since both are Zoho-call-then-local-status-sync flows
against the same Subscription row, mirroring each other's shape.
"""

from datetime import datetime

from fastapi import APIRouter, HTTPException, status, Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.subscription import Subscription
from app.schemas.common import SuccessResponse, SubscriptionCancelRequest, SubscriptionReactivateRequest
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


@router.post("/zoho/subscriptions/reactivate", response_model=SuccessResponse[dict])
async def reactivate_zoho_subscription(
    reactivate_request: SubscriptionReactivateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> SuccessResponse[dict]:
    """
    Reactivate a cancelled subscription in Zoho and update local database.
    Calls Zoho POST /subscriptions/{subscription_id}/reactivate and sets local subscription status to active.
    Reference: https://www.zoho.com/billing/api/v1/subscription/#reactivate-subscription
    This endpoint is additive only: it does not modify cancel/create/validatePayment or any other existing flow.
    """
    try:
        # Require authenticated user
        user = await get_current_user_required(request)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unauthorized"
            )
        subscription_id = reactivate_request.subscriptionId
        platform_name = reactivate_request.platform_name
        billing_cycles = reactivate_request.billingCycles if reactivate_request.billingCycles is not None else 12
        zoho_service_instance = get_zoho_service(platform_name)
        # Call Zoho API to reactivate subscription (Zoho requires billing_cycles in body)
        try:
            zoho_response = await zoho_service_instance.reactivate_subscription(
                subscription_id=subscription_id,
                billing_cycles=billing_cycles
            )
            if not zoho_response:
                return SuccessResponse(
                    success=False,
                    data=None,
                    message="Failed to reactivate subscription in Zoho",
                    code=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
            # Update local subscription: set status to active and clear cancel-at-period-end flag
            subscription_result = await db.execute(
                select(Subscription)
                .where(Subscription.zoho_subscription_id == subscription_id)
                .order_by(Subscription.created_at.desc())
                .limit(1)
            )
            subscription = subscription_result.scalar_one_or_none()
            if subscription:
                # Safely get subscription object from Zoho response (may be nested or top-level)
                subscription_data = zoho_response.get("subscription") if isinstance(zoho_response, dict) else {}
                if not isinstance(subscription_data, dict):
                    subscription_data = {}
                zoho_status = subscription_data.get("status", "live")
                local_status = "active" if zoho_status in ("live", "active") else zoho_status
                update_values = {
                    "status": local_status,
                    "subscription_status": local_status,
                    "zoho_cancel_at_period_end": False,
                    "updated_at": datetime.utcnow(),
                }
                # Optionally sync next_billing_at / current_term_ends_at from Zoho if present
                next_billing_at = subscription_data.get("next_billing_at")
                if next_billing_at:
                    try:
                        update_values["next_billing_date"] = datetime.strptime(next_billing_at, "%Y-%m-%d")
                    except Exception:
                        pass
                current_term_ends_at = subscription_data.get("current_term_ends_at")
                if current_term_ends_at:
                    try:
                        update_values["current_period_end"] = datetime.strptime(current_term_ends_at, "%Y-%m-%d")
                    except Exception:
                        pass
                await db.execute(
                    update(Subscription).where(Subscription.id == subscription.id).values(**update_values)
                )
                await db.commit()
                logger.info(f"✅ Subscription {subscription_id} reactivated in Zoho and local DB set to {local_status}")
            else:
                logger.warning(f"⚠️ Subscription with zoho_subscription_id {subscription_id} not found in local database")
            return SuccessResponse(
                success=True,
                data=zoho_response,
                message="Subscription reactivated successfully",
                code=status.HTTP_200_OK
            )
        except Exception as zoho_error:
            logger.error(f"Zoho API error on reactivate: {zoho_error}")
            err_str = str(zoho_error)
            # Zoho validation errors (invalid subscription ID 107202, invalid billing cycles 101017, etc.) → 400 Bad Request
            if "400" in err_str and ("107202" in err_str or "101017" in err_str or "valid" in err_str.lower()):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=err_str.replace("Zoho API error: 400 - ", "").strip() or "Invalid request to Zoho (check subscription ID and billing cycles)."
                )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to reactivate subscription: {err_str}"
            )
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Exception at reactivate subscription: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}"
        )
