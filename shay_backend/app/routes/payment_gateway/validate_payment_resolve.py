"""
Hosted-page / subscription-id resolution for validate_payment.

Extracted from validate_payment.py (Raven style compliance, wave B): calls
Zoho to retrieve either the hosted page or the subscription directly,
depending on which identifier was provided, and extracts the raw
subscription/invoice payload the caller needs to validate.
"""

import logging
from typing import Any, Optional, Tuple

from fastapi import status

from app.schemas.common import SuccessResponse

logger = logging.getLogger(__name__)


async def _resolve_subscription_data(
    zoho_service_instance: Any,
    hosted_page_id: Optional[str],
    subscription_id: Optional[str],
) -> Tuple[Optional[dict], Optional[dict], Optional[str], Optional[SuccessResponse]]:
    """
    Returns (subscription_data, invoice_data, subscription_id, error_response).

    `error_response` is a ready-to-return SuccessResponse(success=False, ...)
    when resolution fails; the caller should return it as-is. Otherwise it's
    None and subscription_data/invoice_data/subscription_id are populated.
    """
    subscription_data = None
    invoice_data = None

    # If hostedPageId is provided, retrieve hosted page
    if hosted_page_id:
        try:
            zoho_response = await zoho_service_instance.get_hosted_page(hosted_page_id)

            # Extract subscription data from response
            # According to Zoho API, subscription data is in response.data.subscription
            data = zoho_response.get('data', {})
            subscription_data = data.get('subscription', {})
            invoice_data = data.get('invoice', {})

            if not subscription_data:
                logger.warning(f"No subscription data found in hosted page response")
                return None, None, subscription_id, SuccessResponse(
                    success=False,
                    data=None,
                    message="Payment validation failed: No subscription data found",
                    code=status.HTTP_400_BAD_REQUEST
                )

            # Get subscription_id from subscription data if not already provided
            if not subscription_id:
                subscription_id = subscription_data.get('subscription_id')

        except Exception as zoho_error:
            logger.error(f"Zoho API error retrieving hosted page: {zoho_error}")
            return None, None, subscription_id, SuccessResponse(
                success=False,
                data=None,
                message=f"Failed to retrieve hosted page: {str(zoho_error)}",
                code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    # If subscriptionId is provided but no subscription_data yet, fetch subscription directly
    elif subscription_id:
        try:
            subscription_response = await zoho_service_instance.get_subscription(subscription_id)
            subscription_data = subscription_response.get('subscription', {})

            if not subscription_data:
                logger.warning(f"No subscription data found for subscription {subscription_id}")
                return None, None, subscription_id, SuccessResponse(
                    success=False,
                    data=None,
                    message="Payment validation failed: No subscription data found",
                    code=status.HTTP_400_BAD_REQUEST
                )
        except Exception as zoho_error:
            logger.error(f"Zoho API error retrieving subscription: {zoho_error}")
            return None, None, subscription_id, SuccessResponse(
                success=False,
                data=None,
                message=f"Failed to retrieve subscription: {str(zoho_error)}",
                code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    else:
        return None, None, subscription_id, SuccessResponse(
            success=False,
            data=None,
            message="Either hostedPageId or subscriptionId must be provided",
            code=status.HTTP_400_BAD_REQUEST
        )

    return subscription_data, invoice_data, subscription_id, None
