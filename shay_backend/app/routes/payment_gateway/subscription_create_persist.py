"""
DB upsert helper for create_zoho_subscription (subscription_create.py).
Split out of that ~260-line handler so the orchestrator can stay small; see
subscription_create.py's module docstring for the split rationale.
"""

import logging
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from app.models.company import Company
from app.models.subscription_plan import SubscriptionPlan
from app.models.subscription import Subscription

logger = logging.getLogger(__name__)


async def persist_subscription_and_company(
    db: AsyncSession,
    company: Company,
    plan: Optional[SubscriptionPlan],
    plan_code: Optional[str],
    zoho_subscription: dict,
    zoho_subscription_id: str,
    zoho_customer_id: Optional[str],
    fields: dict,
    metadata: Optional[dict],
) -> None:
    """Upsert the local Subscription row (matched by zoho_subscription_id),
    update the company's subscription_plan, and commit. `fields` is the dict
    returned by subscription_create_dates.parse_subscription_fields."""
    # Check if subscription already exists in local DB (by zoho_subscription_id)
    existing_subscription_result = await db.execute(
        select(Subscription)
        .where(Subscription.zoho_subscription_id == zoho_subscription_id)
        .order_by(Subscription.created_at.desc())
        .limit(1)
    )
    existing_subscription = existing_subscription_result.scalar_one_or_none()

    if existing_subscription:
        # Update existing subscription
        await db.execute(
            update(Subscription)
            .where(Subscription.id == existing_subscription.id)
            .values(
                status=fields["local_status"],
                subscription_status=fields["local_status"],
                zoho_customer_id=zoho_customer_id,
                amount=Decimal(str(zoho_subscription.get('amount', 0))),
                currency_code=zoho_subscription.get('currency_code', 'USD'),
                billing_cycle=fields["billing_cycle"],
                auto_collect=zoho_subscription.get('auto_collect', True),
                current_period_start=fields["current_period_start"],
                current_period_end=fields["current_period_end"],
                next_billing_date=fields["next_billing_date"],
                updated_at=datetime.utcnow()
            )
        )
    else:
        # Create new subscription in local database
        subscription = Subscription(
            id=uuid.uuid4(),
            company_id=company.id,
            plan_id=plan.id if plan else None,
            status=fields["local_status"],
            subscription_status=fields["local_status"],
            amount=Decimal(str(zoho_subscription.get('amount', 0))),
            currency_code=zoho_subscription.get('currency_code', 'USD'),
            billing_cycle=fields["billing_cycle"],
            auto_collect=zoho_subscription.get('auto_collect', True),
            current_period_start=fields["current_period_start"],
            current_period_end=fields["current_period_end"],
            next_billing_date=fields["next_billing_date"],
            zoho_subscription_id=zoho_subscription_id,
            zoho_customer_id=zoho_customer_id,
            usage_limits=metadata,  # Store metadata in usage_limits JSONB field
            created_at=fields["created_time"],
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
