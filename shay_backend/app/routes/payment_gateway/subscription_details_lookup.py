"""
Company/subscription/plan lookups for fetch_company_subscription_details.

Extracted from subscription_details.py: pure DB read helpers that resolve
the company, its active subscription, and the subscription's plan, plus the
initial plan/subscription summary dict.
"""
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company import Company
from app.models.subscription import Subscription
from app.models.subscription_plan import SubscriptionPlan


async def _fetch_company(db: AsyncSession, company_id: Any) -> Optional[Company]:
    result = await db.execute(select(Company).where(Company.id == company_id))
    return result.scalar_one_or_none()


async def _fetch_active_subscription(db: AsyncSession, company_id: Any) -> Optional[Subscription]:
    # Get the active subscription for the company (filter by status = 'active')
    result = await db.execute(
        select(Subscription)
        .where(
            Subscription.company_id == company_id,
            Subscription.status == "active"
        )
        .order_by(Subscription.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _fetch_plan(db: AsyncSession, plan_id: Any) -> Optional[SubscriptionPlan]:
    result = await db.execute(select(SubscriptionPlan).where(SubscriptionPlan.id == plan_id))
    return result.scalar_one_or_none()


def _build_plan_summary(plan: SubscriptionPlan, subscription: Subscription) -> Dict[str, Any]:
    """Build the plan/subscription portion of the response_data dict."""
    return {
        "currentPlan": plan.name,
        "currentPlanCode": plan.plan_code,
        "planPeriod": plan.zoho_billing_cycle or f"{plan.interval} {plan.interval_unit}",
        "subscriptionId": subscription.zoho_subscription_id,
        "customerId": subscription.zoho_customer_id,
        "status": subscription.status,
        "currentPlanStatus": subscription.status,
        "currentCost": str(subscription.amount) if subscription.amount else None,
        "nextInvoiceDate": subscription.next_billing_date.isoformat() if subscription.next_billing_date else None,
        "expiresAt": subscription.current_period_end.isoformat() if subscription.current_period_end else None
    }
