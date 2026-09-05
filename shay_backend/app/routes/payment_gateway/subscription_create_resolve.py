"""
Local-plan resolution helper for create_zoho_subscription
(subscription_create.py). Split out of that ~260-line handler so the
orchestrator can stay small; see subscription_create.py's module docstring
for the split rationale.
"""

import logging
from typing import Optional, Tuple

from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.subscription_plan import SubscriptionPlan
from app.schemas.common import SuccessResponse

logger = logging.getLogger(__name__)


def extract_zoho_customer_id(zoho_subscription: dict):
    """customer_id can be in a nested customer object or directly on the
    subscription."""
    if zoho_subscription.get('customer'):
        customer = zoho_subscription['customer']
        return customer.get('customer_id') if isinstance(customer, dict) else customer
    return zoho_subscription.get('customer_id')


async def resolve_local_plan(
    db: AsyncSession, plan_code: Optional[str]
) -> Tuple[Optional[SubscriptionPlan], Optional[SuccessResponse]]:
    """Resolve a local SubscriptionPlan by plan_code (required for the local
    subscription row). Returns (plan, None) on success, or (None,
    error_response) if plan_code was given but no matching local plan was
    found. If plan_code is falsy, returns (None, None) unchanged from the
    original inline behavior."""
    if not plan_code:
        return None, None

    plan_result = await db.execute(
        select(SubscriptionPlan).where(SubscriptionPlan.plan_code == plan_code)
    )
    plan = plan_result.scalar_one_or_none()
    if not plan:
        logger.warning(f"Plan with code {plan_code} not found in local database")
        # Plan must exist locally to create subscription (plan_id is required in DB)
        return None, SuccessResponse(
            success=False,
            data=None,
            message=f"Plan with code {plan_code} not found in local database. Please ensure the plan exists before creating subscription.",
            code=status.HTTP_400_BAD_REQUEST
        )

    return plan, None
