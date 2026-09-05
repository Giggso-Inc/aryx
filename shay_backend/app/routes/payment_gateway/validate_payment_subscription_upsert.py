"""
Find-or-create Subscription upsert for validate_payment_persist.

Extracted from validate_payment.py's DB-persist block (Raven style
compliance, wave B): updates the existing local Subscription row matching
the Zoho subscription id, or creates a new one from the plan looked up by
plan_code.
"""

import logging
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.subscription import Subscription
from app.models.subscription_plan import SubscriptionPlan

logger = logging.getLogger(__name__)


async def _upsert_local_subscription(
    db: AsyncSession,
    company_id: Any,
    subscription_data: dict,
    subscription_id_from_data: str,
    subscription_amount: Any,
    customer_id: Any,
    plan_code: Optional[str],
    created_time: Optional[datetime],
    next_billing_date: Optional[datetime],
) -> None:
    """Update the matching local Subscription row, or create a new one."""
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
        return

    # Create new subscription - we need plan_id from plan_code
    plan_result = await db.execute(
        select(SubscriptionPlan).where(SubscriptionPlan.plan_code == plan_code)
    )
    plan_obj = plan_result.scalar_one_or_none()

    if not plan_obj:
        logger.warning(f"Plan with code {plan_code} not found in local database")
        return

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
