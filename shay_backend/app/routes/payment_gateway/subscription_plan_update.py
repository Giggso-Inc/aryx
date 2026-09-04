"""
POST /zoho/subscriptions/updateCompanyPlan   update_company_plan
(mounted at /api/v1/payment-gateway)
"""

import uuid
from datetime import datetime, timedelta
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, status, Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.company import Company
from app.models.subscription_plan import SubscriptionPlan
from app.models.subscription import Subscription
from app.schemas.common import SuccessResponse

router = APIRouter()


@router.post("/zoho/subscriptions/updateCompanyPlan", response_model=SuccessResponse[dict])
async def update_company_plan(
    request_data: Dict[str, Any],
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> SuccessResponse[dict]:
    """
    Update company plan after successful payment.

    This endpoint updates the company's subscription plan in the local database only.
    The Zoho subscription has already been created/updated through the hosted page flow,
    so this endpoint only needs to sync the local database with the new plan.

    Flow:
    1. Frontend calls hostedPage/create → Creates hosted page in Zoho
    2. User completes payment on Zoho hosted page
    3. Frontend calls fetchByHostedId → Gets payment status
    4. Frontend calls this endpoint → Updates local database only
    """
    try:

        # Get current user for authentication
        user = await get_current_user_required(request)

        # Verify user is company admin
        if user.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only company admins can update company plans"
            )

        # Extract request data
        company_id = request_data.get("companyId")
        new_plan_id = request_data.get("newPlanId")
        subscription_id = request_data.get("subscriptionId")
        hosted_page_id = request_data.get("hostedPageId")
        customer_id = request_data.get("zohoCustomerId")  # Changed from customerId to zohoCustomerId
        platform_name = request_data.get("platform_name")

        if not company_id or not new_plan_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Company ID and new plan ID are required"
            )

        # Check if organization exists
        company_result = await db.execute(
            select(Company).where(Company.id == company_id)
        )
        company = company_result.scalar_one_or_none()

        if not company:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Organization not found"
            )

        # Check if plan exists
        plan_result = await db.execute(
            select(SubscriptionPlan).where(SubscriptionPlan.id == new_plan_id)
        )
        plan = plan_result.scalar_one_or_none()

        if not plan:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Plan not found"
            )

        # Mark all previous active subscriptions for this company as inactive
        # This allows us to track subscription history while keeping only one active subscription
        await db.execute(
            update(Subscription)
            .where(
                Subscription.company_id == company_id,
                Subscription.status.in_(["active", "trial"])
            )
            .values(
                status="inactive",
                subscription_status="inactive",
                updated_at=datetime.utcnow()
            )
        )

        # Always create a new subscription to track upgrade history
        subscription_id_new = uuid.uuid4()
        # Determine billing cycle and period end
        billing_cycle = plan.zoho_billing_cycle or (plan.interval_unit if plan.interval_unit else "monthly")
        # Ensure billing_cycle is a string and handle edge cases
        if not billing_cycle or not isinstance(billing_cycle, str):
            billing_cycle = "monthly"
        if billing_cycle.lower() in ["yearly", "year", "annual"]:
            period_days = 365
        else:
            period_days = 30  # Default to monthly

        current_period_start = datetime.utcnow()
        current_period_end = current_period_start + timedelta(days=period_days)

        new_subscription = Subscription(
            id=subscription_id_new,
            company_id=company_id,
            plan_id=new_plan_id,
            status="active",
            subscription_status="active",
            amount=plan.monthly_price,
            currency_code="USD",
            billing_cycle=billing_cycle,
            auto_collect=True,
            current_period_start=current_period_start,
            current_period_end=current_period_end,
            next_billing_date=current_period_end,
            zoho_subscription_id=subscription_id,
            zoho_customer_id=customer_id,
            zoho_payment_id=hosted_page_id,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        db.add(new_subscription)

        # Update company subscription plan
        await db.execute(
            update(Company)
            .where(Company.id == company_id)
            .values(
                subscription_plan=plan.plan_code,
                updated_at=datetime.utcnow()
            )
        )

        # Note: No need to update Zoho subscription here because:
        # 1. The hosted page creation already created/updated the subscription in Zoho
        # 2. The payment was processed through Zoho's hosted page
        # 3. This endpoint only needs to update the local database to reflect the new plan
        print(f"✅ Local database updated successfully for company {company_id} with plan {new_plan_id}")

        await db.commit()

        return SuccessResponse(
            success=True,
            data={
                "companyId": company_id,
                "newPlanId": new_plan_id,
                "subscriptionId": subscription_id,
                "hostedPageId": hosted_page_id,
                "zohoCustomerId": customer_id  # Changed from customerId to zohoCustomerId
            },
            message="Company plan updated successfully",
            code=status.HTTP_200_OK
        )

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update company plan: {str(e)}"
        )
