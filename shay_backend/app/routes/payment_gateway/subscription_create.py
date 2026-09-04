"""
POST /zoho/subscriptions/create   create_zoho_subscription
(mounted at /api/v1/payment-gateway)

Stated exception: this handler is ~260 lines on its own, well over the
~150-line-per-file target for the whole module. It is one atomic
request/response flow — call Zoho, parse the Zoho response fields (dates,
billing cycle, customer/plan ids), then upsert the local Subscription and
Company rows to match — and splitting the date-parsing or upsert logic into
separate files would fragment a single transaction's steps without
isolating any independently reusable concern, while leaving the total line
count unchanged.
"""

import json
import re
import uuid
from datetime import datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, HTTPException, status, Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.company import Company
from app.models.subscription_plan import SubscriptionPlan
from app.models.subscription import Subscription
from app.schemas.common import SuccessResponse, SubscriptionCreateRequest
from app.services.zoho_service import get_zoho_service

import logging

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

            # Extract customer_id - can be in customer object or directly in subscription
            zoho_customer_id = None
            if zoho_subscription.get('customer'):
                if isinstance(zoho_subscription['customer'], dict):
                    zoho_customer_id = zoho_subscription['customer'].get('customer_id')
                else:
                    zoho_customer_id = zoho_subscription['customer']
            elif zoho_subscription.get('customer_id'):
                zoho_customer_id = zoho_subscription.get('customer_id')

            if not zoho_subscription_id:
                return SuccessResponse(
                    success=False,
                    data=None,
                    message="Zoho subscription ID not found in response",
                    code=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

            # Get plan details from Zoho response or local database
            zoho_plan = zoho_subscription.get('plan', {})
            plan_code = zoho_plan.get('plan_code')
            plan_name = zoho_plan.get('name')

            # Try to find local plan by plan_code (required for local subscription)
            plan = None
            if plan_code:
                plan_result = await db.execute(
                    select(SubscriptionPlan).where(SubscriptionPlan.plan_code == plan_code)
                )
                plan = plan_result.scalar_one_or_none()
                if not plan:
                    logger.warning(f"Plan with code {plan_code} not found in local database")
                    # Plan must exist locally to create subscription (plan_id is required in DB)
                    return SuccessResponse(
                        success=False,
                        data=None,
                        message=f"Plan with code {plan_code} not found in local database. Please ensure the plan exists before creating subscription.",
                        code=status.HTTP_400_BAD_REQUEST
                    )

            # Parse dates from Zoho response
            created_time_str = zoho_subscription.get('created_time')
            next_billing_at_str = zoho_subscription.get('next_billing_at')
            expires_at_str = zoho_subscription.get('expires_at')

            created_time = datetime.utcnow()
            if created_time_str:
                try:
                    # Parse ISO format: "2016-06-11T17:57:13-0700" or "2016-06-11"
                    match = re.match(r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})', created_time_str)
                    if match:
                        created_time = datetime.strptime(match.group(1), "%Y-%m-%dT%H:%M:%S")
                    else:
                        created_time = datetime.strptime(created_time_str.split('T')[0], "%Y-%m-%d")
                except Exception as date_error:
                    logger.warning(f"Could not parse created_time: {date_error}")
                    created_time = datetime.utcnow()

            next_billing_date = None
            if next_billing_at_str:
                try:
                    next_billing_date = datetime.strptime(next_billing_at_str, "%Y-%m-%d")
                except Exception as date_error:
                    logger.warning(f"Could not parse next_billing_at: {date_error}")

            # Note: expires_at is stored as string in Java code, but we'll parse it if needed
            # For now, we'll store it in usage_limits or skip if not critical

            # Determine billing cycle and period end
            interval = zoho_subscription.get('interval', 1)
            interval_unit = zoho_subscription.get('interval_unit', 'months')
            billing_cycle = f"{interval} {interval_unit}"

            if interval_unit.lower() in ["year", "years"]:
                period_days = 365 * interval
            else:
                period_days = 30 * interval

            current_term_starts_at = zoho_subscription.get('current_term_starts_at')
            current_term_ends_at = zoho_subscription.get('current_term_ends_at')

            current_period_start = created_time
            if current_term_starts_at:
                try:
                    current_period_start = datetime.strptime(current_term_starts_at, "%Y-%m-%d")
                except:
                    pass

            current_period_end = current_period_start + timedelta(days=period_days)
            if current_term_ends_at:
                try:
                    current_period_end = datetime.strptime(current_term_ends_at, "%Y-%m-%d")
                except:
                    pass

            # Get subscription status from Zoho
            zoho_status = zoho_subscription.get('status', 'active')
            local_status = 'active' if zoho_status in ['live', 'active'] else zoho_status

            # Check if subscription already exists in local DB (by zoho_subscription_id)
            existing_subscription_result = await db.execute(
                select(Subscription)
                .where(Subscription.zoho_subscription_id == zoho_subscription_id)
                .order_by(Subscription.created_at.desc())
                .limit(1)
            )
            existing_subscription = existing_subscription_result.scalar_one_or_none()

            # Prepare metadata if provided
            metadata_json = None
            if subscription_request.metadata:
                metadata_json = json.dumps(subscription_request.metadata)

            if existing_subscription:
                # Update existing subscription
                await db.execute(
                    update(Subscription)
                    .where(Subscription.id == existing_subscription.id)
                    .values(
                        status=local_status,
                        subscription_status=local_status,
                        zoho_customer_id=zoho_customer_id,
                        amount=Decimal(str(zoho_subscription.get('amount', 0))),
                        currency_code=zoho_subscription.get('currency_code', 'USD'),
                        billing_cycle=billing_cycle,
                        auto_collect=zoho_subscription.get('auto_collect', True),
                        current_period_start=current_period_start,
                        current_period_end=current_period_end,
                        next_billing_date=next_billing_date,
                        updated_at=datetime.utcnow()
                    )
                )
                subscription_id = existing_subscription.id
            else:
                # Create new subscription in local database
                subscription_id = uuid.uuid4()
                subscription = Subscription(
                    id=subscription_id,
                    company_id=company.id,
                    plan_id=plan.id if plan else None,
                    status=local_status,
                    subscription_status=local_status,
                    amount=Decimal(str(zoho_subscription.get('amount', 0))),
                    currency_code=zoho_subscription.get('currency_code', 'USD'),
                    billing_cycle=billing_cycle,
                    auto_collect=zoho_subscription.get('auto_collect', True),
                    current_period_start=current_period_start,
                    current_period_end=current_period_end,
                    next_billing_date=next_billing_date,
                    zoho_subscription_id=zoho_subscription_id,
                    zoho_customer_id=zoho_customer_id,
                    usage_limits=subscription_request.metadata,  # Store metadata in usage_limits JSONB field
                    created_at=created_time,
                    updated_at=datetime.utcnow()
                )
                db.add(subscription)

            # Update company subscription plan
            if plan_code:
                await db.execute(
                    update(Company)
                    .where(Company.id == company.id)
                    .values(
                        subscription_plan=plan_code,
                        updated_at=datetime.utcnow()
                    )
                )

            await db.commit()
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
