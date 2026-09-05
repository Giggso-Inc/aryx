"""
DB upsert helper for update_company_plan (subscription_plan_update.py).
Split out of that ~150-line handler so the orchestrator can stay small; see
subscription_plan_update.py's module docstring for the split rationale.
"""

import uuid
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import update

from app.models.company import Company
from app.models.subscription_plan import SubscriptionPlan
from app.models.subscription import Subscription


def _resolve_billing_cycle(plan: SubscriptionPlan) -> tuple[str, int]:
    """Returns (billing_cycle, period_days) for a new subscription row."""
    billing_cycle = plan.zoho_billing_cycle or (plan.interval_unit if plan.interval_unit else "monthly")
    # Ensure billing_cycle is a string and handle edge cases
    if not billing_cycle or not isinstance(billing_cycle, str):
        billing_cycle = "monthly"
    if billing_cycle.lower() in ["yearly", "year", "annual"]:
        period_days = 365
    else:
        period_days = 30  # Default to monthly
    return billing_cycle, period_days


async def replace_active_subscription(
    db: AsyncSession,
    company_id: str,
    new_plan_id: str,
    plan: SubscriptionPlan,
    zoho_subscription_id,
    zoho_customer_id,
    hosted_page_id,
) -> None:
    """Mark all previous active/trial subscriptions for this company as
    inactive, create a new active subscription row for `plan`, update the
    company's subscription_plan, and commit."""
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
    billing_cycle, period_days = _resolve_billing_cycle(plan)
    current_period_start = datetime.utcnow()
    current_period_end = current_period_start + timedelta(days=period_days)

    new_subscription = Subscription(
        id=uuid.uuid4(),
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
        zoho_subscription_id=zoho_subscription_id,
        zoho_customer_id=zoho_customer_id,
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

    await db.commit()
