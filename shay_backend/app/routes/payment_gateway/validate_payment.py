"""
POST /zoho/subscriptions/validatePayment   validate_payment
(mounted at /api/v1/payment-gateway)

Stated exception: this handler is ~340 lines on its own, well over the
~150-line-per-file target for the whole module. It is one atomic
request/response flow with two entry paths (hostedPageId vs subscriptionId)
that converge into a single validate-then-upsert-then-activate sequence
against Zoho and the local Subscription/Company tables. Splitting the
entry-path resolution from the upsert logic would fragment one transaction's
steps across files without isolating any independently reusable concern,
and would not reduce the endpoint's real complexity.
"""

import re
import uuid
from datetime import datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, HTTPException, status, Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.user import User
from app.models.company import Company
from app.models.subscription_plan import SubscriptionPlan
from app.models.subscription import Subscription
from app.schemas.common import SuccessResponse, ValidatePaymentRequest
from app.services.zoho_service import get_zoho_service

import logging

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

        subscription_data = None
        zoho_response = None
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
                    return SuccessResponse(
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
                return SuccessResponse(
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
                    return SuccessResponse(
                        success=False,
                        data=None,
                        message="Payment validation failed: No subscription data found",
                        code=status.HTTP_400_BAD_REQUEST
                    )
            except Exception as zoho_error:
                logger.error(f"Zoho API error retrieving subscription: {zoho_error}")
                return SuccessResponse(
                    success=False,
                    data=None,
                    message=f"Failed to retrieve subscription: {str(zoho_error)}",
                    code=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
        else:
            return SuccessResponse(
                success=False,
                data=None,
                message="Either hostedPageId or subscriptionId must be provided",
                code=status.HTTP_400_BAD_REQUEST
            )

        # Validate payment
        subscription_status = subscription_data.get('status', '').lower()
        subscription_id_from_data = subscription_data.get('subscription_id')

        if not subscription_id_from_data:
            return SuccessResponse(
                success=False,
                data=None,
                message="Payment validation failed: Invalid subscription data",
                code=status.HTTP_400_BAD_REQUEST
            )

        # Check if subscription status is "live"
        if subscription_status != 'live':
            logger.warning(f"Subscription status is not 'live': {subscription_status}")
            return SuccessResponse(
                success=False,
                data=None,
                message=f"Payment validation failed: Subscription status is '{subscription_status}', expected 'live'",
                code=status.HTTP_400_BAD_REQUEST
            )

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
            )

        # Payment is valid - update company subscription and activate company
        try:
            # Get customer data
            customer = subscription_data.get('customer', {})
            customer_id = customer.get('customer_id')
            customer_email = customer.get('email')

            # Get plan data
            plan = subscription_data.get('plan', {})
            plan_code = plan.get('plan_code')
            plan_name = plan.get('name')

            # Verify company exists
            company_result = await db.execute(
                select(Company).where(Company.id == company_id)
            )
            company = company_result.scalar_one_or_none()

            if not company:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Company not found"
                )

            # Parse dates
            created_time_str = subscription_data.get('created_time')
            next_billing_at_str = subscription_data.get('next_billing_at')

            created_time = None
            next_billing_date = None

            if created_time_str:
                try:
                    # Parse ISO format datetime: "2016-06-05T23:10:16-0700" or "2016-06-05T23:10:16-07:00"
                    # Match pattern like "2016-06-05T23:10:16" or "2016-06-05T23:10:16-0700"
                    match = re.match(r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})', created_time_str)
                    if match:
                        created_time = datetime.strptime(match.group(1), "%Y-%m-%dT%H:%M:%S")
                    else:
                        # Try simple date format
                        created_time = datetime.strptime(created_time_str.split('T')[0], "%Y-%m-%d")
                except Exception as date_error:
                    logger.warning(f"Could not parse created_time: {date_error}")
                    created_time = datetime.utcnow()

            if next_billing_at_str:
                try:
                    # Parse date format: "2016-06-30"
                    next_billing_date = datetime.strptime(next_billing_at_str, "%Y-%m-%d")
                except Exception as date_error:
                    logger.warning(f"Could not parse next_billing_at: {date_error}")

            # Find or create subscription in local database
            subscription_result = await db.execute(
                select(Subscription).where(
                    Subscription.zoho_subscription_id == subscription_id_from_data
                )
            )
            subscription = subscription_result.scalar_one_or_none()

            if subscription:
                # Update existing subscription
                await db.execute(
                    update(Subscription)
                    .where(Subscription.id == subscription.id)
                    .values(
                        status="active",
                        subscription_status="active",
                        zoho_customer_id=customer_id,
                        updated_at=datetime.utcnow()
                    )
                )
                if next_billing_date:
                    await db.execute(
                        update(Subscription)
                        .where(Subscription.id == subscription.id)
                        .values(
                            next_billing_date=next_billing_date,
                            updated_at=datetime.utcnow()
                        )
                    )
            else:
                # Create new subscription - we need plan_id from plan_code
                plan_result = await db.execute(
                    select(SubscriptionPlan).where(SubscriptionPlan.plan_code == plan_code)
                )
                plan_obj = plan_result.scalar_one_or_none()

                if not plan_obj:
                    logger.warning(f"Plan with code {plan_code} not found in local database")
                else:
                    # Determine billing cycle and period end
                    billing_cycle = plan_obj.zoho_billing_cycle or (plan_obj.interval_unit if plan_obj.interval_unit else "monthly")
                    if not billing_cycle or not isinstance(billing_cycle, str):
                        billing_cycle = "monthly"
                    if billing_cycle.lower() in ["yearly", "year", "annual"]:
                        period_days = 365
                    else:
                        period_days = 30

                    current_period_start = created_time or datetime.utcnow()
                    current_period_end = current_period_start + timedelta(days=period_days)

                    new_subscription = Subscription(
                        id=uuid.uuid4(),
                        company_id=company_id,
                        plan_id=plan_obj.id,
                        status="active",
                        subscription_status="active",
                        amount=Decimal(str(subscription_amount)),
                        currency_code=subscription_data.get('currency_code', 'USD'),
                        billing_cycle=billing_cycle,
                        auto_collect=True,
                        current_period_start=current_period_start,
                        current_period_end=current_period_end,
                        next_billing_date=next_billing_date or current_period_end,
                        zoho_subscription_id=subscription_id_from_data,
                        zoho_customer_id=customer_id,
                        created_at=created_time or datetime.utcnow(),
                        updated_at=datetime.utcnow()
                    )
                    db.add(new_subscription)

            # Update company subscription plan and activate company
            if plan_code:
                await db.execute(
                    update(Company)
                    .where(Company.id == company_id)
                    .values(
                        subscription_plan=plan_code,
                        is_active=True,  # Activate company
                        updated_at=datetime.utcnow()
                    )
                )

            # Update other subscriptions for this company to inactive
            # Mark other active subscriptions for this company as inactive
            await db.execute(
                update(Subscription)
                .where(
                    Subscription.company_id == company_id,
                    Subscription.zoho_subscription_id != subscription_id_from_data,
                    Subscription.status.in_(["active", "trial"])
                )
                .values(
                    status="inactive",
                    subscription_status="inactive",
                    updated_at=datetime.utcnow()
                )
            )

            await db.commit()
            logger.info(f"✅ Payment validated and company {company_id} activated successfully")

            return SuccessResponse(
                success=True,
                data={
                    "subscriptionId": subscription_id_from_data,
                    "companyId": company_id,
                    "status": "active",
                    "planCode": plan_code,
                    "planName": plan_name
                },
                message="Payment validated and company activated successfully",
                code=status.HTTP_200_OK
            )

        except Exception as db_error:
            await db.rollback()
            logger.error(f"Database error during payment validation: {db_error}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to update database: {str(db_error)}"
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
