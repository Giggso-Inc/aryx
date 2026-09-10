"""
POST / -> create_subscription_plan.

Split from the original 327-line app/routes/subscription_plans.py (Raven
style-compliance pass, see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md,
wave B5).
"""

from datetime import datetime

from fastapi import APIRouter, HTTPException, status, Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.auth import generate_channel_id
from app.middleware.auth_middleware import get_current_user_required
from app.models.subscription_plan import SubscriptionPlan
from app.schemas.subscription_plan import SubscriptionPlanCreate, SubscriptionPlanResponse

router = APIRouter()


@router.post("/", response_model=SubscriptionPlanResponse)
async def create_subscription_plan(
    plan_data: SubscriptionPlanCreate,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> SubscriptionPlanResponse:
    """Create a new subscription plan"""
    user = await get_current_user_required(request)

    # Only admins can create subscription plans
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can create subscription plans"
        )

    # Check if plan code already exists
    existing_plan = await db.execute(
        select(SubscriptionPlan).where(SubscriptionPlan.plan_code == plan_data.plan_code)
    )
    if existing_plan.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Plan with code '{plan_data.plan_code}' already exists"
        )

    # Create new plan
    plan = SubscriptionPlan(
        id=generate_channel_id(),  # Reuse the generator for UUID
        name=plan_data.name,
        plan_code=plan_data.plan_code,
        description=plan_data.description,
        monthly_price=plan_data.monthly_price,
        plan_cycles=plan_data.plan_cycles,
        interval=plan_data.interval,
        interval_unit=plan_data.interval_unit,
        interval_count=plan_data.interval_count,
        features=plan_data.features,
        sort_order=plan_data.sort_order,
        is_active=plan_data.is_active,
        zoho_plan_id=plan_data.zoho_plan_id,
        zoho_product_id=plan_data.zoho_product_id,
        zoho_plan_code=plan_data.zoho_plan_code,
        zoho_product_code=plan_data.zoho_product_code,
        zoho_billing_cycle=plan_data.zoho_billing_cycle,
        created_by=user.id,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )

    db.add(plan)
    await db.commit()
    await db.refresh(plan)

    return plan
