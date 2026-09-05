"""
POST /zoho/subscriptions/create   create_zoho_subscription
(mounted at /api/v1/payment-gateway)

Thin orchestrator: resolves the user/company, calls Zoho, then delegates
local-plan resolution (subscription_create_resolve.py), date/status parsing
(subscription_create_dates.py), and the DB upsert
(subscription_create_persist.py) to sibling helper modules. Split from a
single ~260-line handler (Raven style compliance, wave B).
get_current_user_required and get_zoho_service stay bound in THIS module
because tests/test_payment_gateway_characterization.py patches them on
`app.routes.payment_gateway.subscription_create`.
"""

import logging

from fastapi import APIRouter, HTTPException, status, Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.company import Company
from app.schemas.common import SuccessResponse, SubscriptionCreateRequest
from app.services.zoho_service import get_zoho_service

from .subscription_create_resolve import resolve_local_plan, extract_zoho_customer_id
from .subscription_create_dates import parse_subscription_fields
from .subscription_create_persist import persist_subscription_and_company

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/zoho/subscriptions/create", response_model=SuccessResponse[dict])
async def create_zoho_subscription(
    subscription_request: SubscriptionCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> SuccessResponse[dict]:
    """
    Create a subscription in Zoho and save to local database.

    This endpoint creates a subscription in Zoho first, then saves the subscription
    details to the local database with the Zoho subscription_id.

    Reference: https://www.zoho.com/billing/api/v1/subscription/#create-a-subscription
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
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unauthorized"
            )

        # Get company
        company_result = await db.execute(
            select(Company).where(Company.id == user.company_id)
        )
        company = company_result.scalar_one_or_none()

        if not company:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Company not found"
            )

        platform_name = subscription_request.platform_name
        zoho_service_instance = get_zoho_service(platform_name)

        # Convert Pydantic model to dict for Zoho service
        subscription_data = subscription_request.model_dump(exclude_none=True)

        # Call Zoho API to create subscription
        try:
            zoho_response = await zoho_service_instance.create_subscription(subscription_data)

            if not zoho_response or not zoho_response.get('subscription'):
                return SuccessResponse(
                    success=False,
                    data=None,
                    message="Failed to create subscription in Zoho",
                    code=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

            # Extract subscription data from Zoho response
            zoho_subscription = zoho_response.get('subscription', {})
            zoho_subscription_id = zoho_subscription.get('subscription_id')
            zoho_customer_id = extract_zoho_customer_id(zoho_subscription)

            if not zoho_subscription_id:
                return SuccessResponse(
                    success=False,
                    data=None,
                    message="Zoho subscription ID not found in response",
                    code=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

            # Get plan details from Zoho response, resolve required local plan
            zoho_plan = zoho_subscription.get('plan', {})
            plan_code = zoho_plan.get('plan_code')
            plan, plan_error = await resolve_local_plan(db, plan_code)
            if plan_error:
                return plan_error

            fields = parse_subscription_fields(zoho_subscription)

            await persist_subscription_and_company(
                db, company, plan, plan_code, zoho_subscription,
                zoho_subscription_id, zoho_customer_id, fields,
                subscription_request.metadata,
            )
            logger.info(f"✅ Subscription {zoho_subscription_id} created in Zoho and saved to local database")

            return SuccessResponse(
                success=True,
                data=zoho_response,
                message="Subscription created successfully",
                code=status.HTTP_200_OK
            )

        except Exception as zoho_error:
            logger.error(f"Zoho API error: {zoho_error}")
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to create subscription: {str(zoho_error)}"
            )

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Exception at create subscription: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}"
        )
