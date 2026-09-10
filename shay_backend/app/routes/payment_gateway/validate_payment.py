"""
POST /zoho/subscriptions/validatePayment   validate_payment
(mounted at /api/v1/payment-gateway)

Thin orchestrator: resolves the user, obtains the Zoho service, resolves
the Zoho subscription/invoice payload (hostedPageId or subscriptionId
path), checks the payment status, then delegates the DB upsert + company
activation to sibling helper modules.

Split from a single ~340-line handler (Raven style compliance, wave B):
  - validate_payment_resolve.py -> hosted-page/subscription-id resolution
  - validate_payment_status.py  -> payment/subscription-status check
  - validate_payment_persist.py -> DB upsert + company activation
get_current_user_required and get_zoho_service stay bound in THIS module
because tests/test_payment_gateway_characterization.py patches them on
`app.routes.payment_gateway.validate_payment`.
"""

import logging

from fastapi import APIRouter, HTTPException, status, Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.user import User
from app.schemas.common import SuccessResponse, ValidatePaymentRequest
from app.services.zoho_service import get_zoho_service

from .validate_payment_resolve import _resolve_subscription_data
from .validate_payment_status import _check_payment_status
from .validate_payment_persist import _persist_subscription_and_activate

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/zoho/subscriptions/validatePayment", response_model=SuccessResponse[dict])
async def validate_payment(
    subscription_request: ValidatePaymentRequest,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> SuccessResponse[dict]:
    """
    Validate payment and activate company.

    This endpoint validates payment by checking the hosted page or subscription status
    in Zoho, and if payment is successful, activates the company.

    Reference: https://www.zoho.com/billing/api/v1/hosted-pages/#retrieve-a-hosted-page
    """
    try:
        # Get user - use userId from request if provided, otherwise use current user
        user = None
        if subscription_request.userId:
            user_result = await db.execute(
                select(User).where(User.id == subscription_request.userId)
            )
            user = user_result.scalar_one_or_none()
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User not found"
                )
        else:
            user = await get_current_user_required(request)

        company_id = subscription_request.companyId
        hosted_page_id = subscription_request.hostedPageId
        subscription_id = subscription_request.subscriptionId
        platform_name = subscription_request.platform_name

        # Get appropriate Zoho service instance
        zoho_service_instance = get_zoho_service(platform_name)

        subscription_data, invoice_data, subscription_id, error_response = await _resolve_subscription_data(
            zoho_service_instance, hosted_page_id, subscription_id
        )
        if error_response:
            return error_response

        error_response, subscription_id_from_data, subscription_amount = _check_payment_status(
            subscription_data, invoice_data
        )
        if error_response:
            return error_response

        # Payment is valid - update company subscription and activate company
        return await _persist_subscription_and_activate(
            db, company_id, subscription_data, subscription_id_from_data, subscription_amount
        )

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Exception at validate payment: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}"
        )
