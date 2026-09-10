"""
Zoho hosted-page subscription-update endpoint (mounted at
/api/v1/payment-gateway):
  PUT /zoho/subscriptions/hostedPage/update  update_subscription_hosted_page

Split out of hosted_pages.py to keep each file under the ~150-line target.
"""

from fastapi import APIRouter, HTTPException, status, Request

from app.middleware.auth_middleware import get_current_user_required
from app.schemas.common import SuccessResponse, SubscriptionUpdateRequest
from app.services.zoho_service import get_zoho_service

import logging

logger = logging.getLogger(__name__)

router = APIRouter()


@router.put("/zoho/subscriptions/hostedPage/update", response_model=SuccessResponse[dict])
async def update_subscription_hosted_page(
    subscription_request: SubscriptionUpdateRequest,
    request: Request
) -> SuccessResponse[dict]:
    """
    Create a hosted page for updating a subscription.

    This endpoint creates a Zoho hosted payment page that allows customers
    to update their subscription (change plan, add addons, etc.).

    Reference: https://www.zoho.com/billing/api/v1/hosted-pages/#update-a-subscription
    """
    try:
        # Validate request
        if not subscription_request:
            return SuccessResponse(
                success=False,
                data=None,
                message="Subscription request is required",
                code=status.HTTP_400_BAD_REQUEST
            )

        # Get current user for authentication
        user = await get_current_user_required(request)

        # Verify user is company admin
        if user.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only company admins can update subscriptions"
            )

        # Get platform_name from request
        platform_name = subscription_request.platform_name

        # Get appropriate Zoho service instance based on platform_name
        zoho_service_instance = get_zoho_service(platform_name)

        # Convert Pydantic model to dict for service
        subscription_data = subscription_request.model_dump(exclude_none=True)

        # Call Zoho service to create update subscription hosted page
        try:
            zoho_response = await zoho_service_instance.update_subscription_hosted_page(subscription_data)

            if zoho_response and zoho_response.get('hostedPageId'):
                return SuccessResponse(
                    success=True,
                    data=zoho_response,
                    message="Hosted page for subscription update created successfully",
                    code=status.HTTP_200_OK
                )
            else:
                return SuccessResponse(
                    success=False,
                    data=None,
                    message="Failed to create hosted page for subscription update",
                    code=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

        except Exception as zoho_error:
            logger.error(f"Zoho API error: {zoho_error}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to create hosted page: {str(zoho_error)}"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Exception at update subscription hosted page: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}"
        )
