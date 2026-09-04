"""
Company current-plan endpoints: the authenticated user's own company, and an
arbitrary company by ID.

Split from the original app/routes/subscriptions.py (Raven style-compliance
pass, see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2).

The two endpoints below duplicated an identical "default free plan" response
and an identical "build response from subscription+plan" block in the
original file; that duplication is factored into the two private helpers
below. This is a pure extraction — no behavior changes — so the
characterization tests written before the split still pass unmodified.
"""

from fastapi import APIRouter, HTTPException, status, Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from datetime import datetime, timedelta, timezone

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.subscription import Subscription
from app.models.subscription_plan import SubscriptionPlan
from app.models.company import Company
from app.schemas.subscription import CompanyCurrentPlanResponse

from .helpers import validate_uuid

router = APIRouter()


def _default_free_plan_response() -> CompanyCurrentPlanResponse:
    """The fallback response for a company with no active/trial subscription."""
    now = datetime.now(timezone.utc)
    return CompanyCurrentPlanResponse(
        plan_name="Free Plan",
        plan_code="free",
        billing_cycle="N/A",
        cost=0.00,
        currency_code="USD",
        next_renewal=now + timedelta(days=30),
        status="active",
        features={"max_users": 10, "max_workspaces": 5, "max_storage_gb": 1},
        current_period_start=now,
        current_period_end=now + timedelta(days=30),
        is_trial=False,
        trial_end=None
    )


def _plan_response_from_subscription(
    subscription: Subscription, plan: SubscriptionPlan
) -> CompanyCurrentPlanResponse:
    """Build the response for a company that has an active/trial subscription."""
    is_trial = subscription.status == "trial"
    trial_end = subscription.zoho_trial_end if is_trial else None

    if subscription.next_billing_date:
        next_renewal = subscription.next_billing_date
    else:
        # Estimate based on billing cycle
        if subscription.billing_cycle.lower() == "monthly":
            next_renewal = subscription.current_period_end
        elif subscription.billing_cycle.lower() == "yearly":
            next_renewal = subscription.current_period_end
        else:
            next_renewal = subscription.current_period_end

    return CompanyCurrentPlanResponse(
        plan_name=plan.name,
        plan_code=plan.plan_code,
        billing_cycle=subscription.billing_cycle,
        cost=subscription.amount,
        currency_code=subscription.currency_code,
        next_renewal=next_renewal,
        status=subscription.status,
        features=plan.features,
        current_period_start=subscription.current_period_start,
        current_period_end=subscription.current_period_end,
        is_trial=is_trial,
        trial_end=trial_end
    )


@router.get("/company/my/current-plan", response_model=CompanyCurrentPlanResponse)
async def get_my_company_current_plan(
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> CompanyCurrentPlanResponse:
    """Get current plan details for the authenticated user's company"""
    user = await get_current_user_required(request, db)

    # Check if user has a company_id
    if not user.company_id:
        # Return default free plan info for users without company
        return _default_free_plan_response()

    # Get current active subscription for user's company
    subscription = await db.execute(
        select(Subscription, SubscriptionPlan).join(
            SubscriptionPlan, Subscription.plan_id == SubscriptionPlan.id
        ).where(
            and_(
                Subscription.company_id == user.company_id,
                Subscription.status.in_(["active", "trial"]),
                Subscription.deleted_at.is_(None)
            )
        ).order_by(Subscription.created_at.desc())
    )
    subscription_data = subscription.first()

    if not subscription_data:
        # Return default free plan info
        return _default_free_plan_response()

    subscription, plan = subscription_data
    return _plan_response_from_subscription(subscription, plan)


@router.get("/company/{company_id}/current-plan", response_model=CompanyCurrentPlanResponse)
async def get_company_current_plan(
    company_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> CompanyCurrentPlanResponse:
    """Get current plan details for a company"""
    user = await get_current_user_required(request, db)

    company_uuid = validate_uuid(company_id, "company ID")

    # Check if company exists
    company = await db.execute(
        select(Company).where(Company.id == company_uuid)
    )
    company = company.scalar_one_or_none()

    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company not found"
        )

    # Only admins or company members can view company plan
    if not user.is_admin and str(user.company_id) != str(company_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to company plan"
        )

    # Get current active subscription
    subscription = await db.execute(
        select(Subscription, SubscriptionPlan).join(
            SubscriptionPlan, Subscription.plan_id == SubscriptionPlan.id
        ).where(
            and_(
                Subscription.company_id == company_uuid,
                Subscription.status.in_(["active", "trial"]),
                Subscription.deleted_at.is_(None)
            )
        ).order_by(Subscription.created_at.desc())
    )
    subscription_data = subscription.first()

    if not subscription_data:
        # Return default free plan info
        return _default_free_plan_response()

    subscription, plan = subscription_data
    return _plan_response_from_subscription(subscription, plan)
