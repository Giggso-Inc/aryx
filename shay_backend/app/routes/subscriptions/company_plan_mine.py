"""GET /company/my/current-plan — get_my_company_current_plan.

Must be registered before company_plan_by_id.py's dynamic
GET /company/{company_id}/current-plan — a literal path segment ("my")
would otherwise be captured by the dynamic {company_id} segment.

Split from the original company_plan.py (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Wave B4).
"""

from fastapi import APIRouter, Depends, Request
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.subscription import Subscription
from app.models.subscription_plan import SubscriptionPlan
from app.schemas.subscription import CompanyCurrentPlanResponse

from .company_plan_shared import default_free_plan_response, plan_response_from_subscription

router = APIRouter()


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
        return default_free_plan_response()

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
        return default_free_plan_response()

    subscription, plan = subscription_data
    return plan_response_from_subscription(subscription, plan)
