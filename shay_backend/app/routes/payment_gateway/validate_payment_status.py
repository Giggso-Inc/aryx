"""
Payment-status check for validate_payment.

Extracted from validate_payment.py (Raven style compliance, wave B): given
the resolved Zoho subscription/invoice payload, verifies the subscription
is "live" and the invoice (if present) shows payment made.
"""

import logging
from typing import Any, Optional, Tuple

from fastapi import status

from app.schemas.common import SuccessResponse

logger = logging.getLogger(__name__)


def _check_payment_status(
    subscription_data: dict,
    invoice_data: Optional[dict],
) -> Tuple[Optional[SuccessResponse], Optional[str], Any]:
    """
    Returns (error_response, subscription_id_from_data, subscription_amount).
    `error_response` is a ready-to-return SuccessResponse(success=False, ...)
    when validation fails; otherwise None and the other two are populated.
    """
    subscription_status = subscription_data.get('status', '').lower()
    subscription_id_from_data = subscription_data.get('subscription_id')

    if not subscription_id_from_data:
        return SuccessResponse(
            success=False,
            data=None,
            message="Payment validation failed: Invalid subscription data",
            code=status.HTTP_400_BAD_REQUEST
        ), None, None

    # Check if subscription status is "live"
    if subscription_status != 'live':
        logger.warning(f"Subscription status is not 'live': {subscription_status}")
        return SuccessResponse(
            success=False,
            data=None,
            message=f"Payment validation failed: Subscription status is '{subscription_status}', expected 'live'",
            code=status.HTTP_400_BAD_REQUEST
        ), None, None

    # Validate payment - check if there's an invoice with payment made
    # Basic payment validation - check if subscription has amount > 0
    # In a real scenario, you might want to check invoice payment_made > 0 or balance == 0
    subscription_amount = subscription_data.get('amount', 0)
    is_payment_valid = True

    # If there's invoice data, check payment status
    if invoice_data:
        payment_made = invoice_data.get('payment_made', 0)
        balance = invoice_data.get('balance', 0)
        # Payment is valid if payment_made > 0 or balance == 0
        is_payment_valid = payment_made > 0 or balance == 0
    else:
        # If no invoice data, assume payment is valid if subscription status is "live"
        # This is a basic validation - in production, you might want stricter checks
        is_payment_valid = True

    if not is_payment_valid:
        logger.warning(f"Payment validation failed: Payment not confirmed")
        return SuccessResponse(
            success=False,
            data=None,
            message="Payment validation failed: Payment not confirmed",
            code=status.HTTP_400_BAD_REQUEST
        ), None, None

    return None, subscription_id_from_data, subscription_amount
