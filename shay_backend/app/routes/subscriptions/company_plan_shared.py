"""
Shared response-building helpers for the company current-plan endpoints
(company_plan_mine.py and company_plan_by_id.py).

Split from the original company_plan.py (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Wave B4). The two endpoints
duplicated an identical "default free plan" response and an identical
"build response from subscription+plan" block; that duplication is factored
into the two helpers below. This is a pure extraction — no behavior
changes — so the characterization tests written before the split still
pass unmodified.
"""

from datetime import datetime, timedelta, timezone

from app.models.subscription import Subscription
from app.models.subscription_plan import SubscriptionPlan
from app.schemas.subscription import CompanyCurrentPlanResponse


def default_free_plan_response() -> CompanyCurrentPlanResponse:
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


def plan_response_from_subscription(
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
