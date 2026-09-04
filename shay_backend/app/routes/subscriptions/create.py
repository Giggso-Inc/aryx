"""
POST / — create_subscription.

Split from the original app/routes/subscriptions.py (Raven style-compliance
pass, see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2).
"""

from fastapi import APIRouter, HTTPException, status, Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from datetime import datetime, timezone

from app.core.database import get_db
from app.core.auth import generate_channel_id
from app.middleware.auth_middleware import get_current_user_required
from app.models.subscription import Subscription
from app.models.subscription_plan import SubscriptionPlan
from app.models.company import Company
from app.schemas.subscription import SubscriptionCreate, SubscriptionResponse

router = APIRouter()


@router.post("/", response_model=SubscriptionResponse)
async def create_subscription(
    subscription_data: SubscriptionCreate,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> SubscriptionResponse:
    """Create a new subscription for a company"""
    user = await get_current_user_required(request, db)

    # Only admins can create subscriptions
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can create subscriptions"
        )

    # Validate company exists
    company = await db.execute(
        select(Company).where(Company.id == subscription_data.company_id)
    )
    company = company.scalar_one_or_none()

    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company not found"
        )

    # Validate plan exists
    plan = await db.execute(
        select(SubscriptionPlan).where(SubscriptionPlan.id == subscription_data.plan_id)
    )
    plan = plan.scalar_one_or_none()

    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subscription plan not found"
        )

    # Check if company already has an active subscription to this plan
    existing_subscription = await db.execute(
        select(Subscription).where(
            and_(
                Subscription.company_id == subscription_data.company_id,
                Subscription.plan_id == subscription_data.plan_id,
                Subscription.status.in_(["active", "trial"])
            )
        )
    )
    if existing_subscription.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Company already has an active subscription to this plan"
        )

    # Create new subscription
    subscription = Subscription(
        id=generate_channel_id(),  # Reuse the generator for UUID
        company_id=subscription_data.company_id,
        plan_id=subscription_data.plan_id,
        status=subscription_data.status,
        subscription_status=subscription_data.subscription_status,
        amount=subscription_data.amount,
        currency_code=subscription_data.currency_code,
        billing_cycle=subscription_data.billing_cycle,
        auto_collect=subscription_data.auto_collect,
        current_period_start=subscription_data.current_period_start,
        current_period_end=subscription_data.current_period_end,
        next_billing_date=subscription_data.next_billing_date,
        zoho_trial_end=subscription_data.zoho_trial_end,
        zoho_cancel_at_period_end=subscription_data.zoho_cancel_at_period_end,
        usage_limits=subscription_data.usage_limits,
        zoho_subscription_id=subscription_data.zoho_subscription_id,
        zoho_customer_id=subscription_data.zoho_customer_id,
        zoho_hosted_page_id=subscription_data.zoho_hosted_page_id,
        zoho_invoice_id=subscription_data.zoho_invoice_id,
        zoho_payment_id=subscription_data.zoho_payment_id,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc)
    )

    db.add(subscription)
    await db.commit()
    await db.refresh(subscription)

    return subscription
