"""
GET /active/plans -> get_active_plans.

Split from the original 327-line app/routes/subscription_plans.py (Raven
style-compliance pass, see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md,
wave B5).
"""

from typing import List

from fastapi import APIRouter, Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.subscription_plan import SubscriptionPlan
from app.schemas.subscription_plan import SubscriptionPlanResponse

router = APIRouter()


@router.get("/active/plans", response_model=List[SubscriptionPlanResponse])
async def get_active_plans(
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> List[SubscriptionPlanResponse]:
    """Get all active subscription plans"""
    user = await get_current_user_required(request)

    result = await db.execute(
        select(SubscriptionPlan)
        .where(SubscriptionPlan.is_active == True)
        .order_by(SubscriptionPlan.sort_order.asc())
    )
    plans = result.scalars().all()

    return plans
