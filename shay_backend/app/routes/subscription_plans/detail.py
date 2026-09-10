"""
GET/PUT/DELETE /{plan_id} -> get_subscription_plan, update_subscription_plan,
delete_subscription_plan.

Split from the original 327-line app/routes/subscription_plans.py (Raven
style-compliance pass, see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md,
wave B5).
"""

from datetime import datetime

from fastapi import APIRouter, HTTPException, status, Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.subscription_plan import SubscriptionPlan
from app.schemas.subscription_plan import SubscriptionPlanUpdate, SubscriptionPlanResponse

from .helpers import validate_uuid

router = APIRouter()


@router.get("/{plan_id}", response_model=SubscriptionPlanResponse)
async def get_subscription_plan(
    plan_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> SubscriptionPlanResponse:
    """Get subscription plan by ID"""
    user = await get_current_user_required(request)

    plan_uuid = validate_uuid(plan_id, "plan ID")

    plan = await db.execute(
        select(SubscriptionPlan).where(SubscriptionPlan.id == plan_uuid)
    )
    plan = plan.scalar_one_or_none()

    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subscription plan not found"
        )

    return plan


@router.put("/{plan_id}", response_model=SubscriptionPlanResponse)
async def update_subscription_plan(
    plan_id: str,
    plan_data: SubscriptionPlanUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> SubscriptionPlanResponse:
    """Update subscription plan"""
    user = await get_current_user_required(request)

    # Only admins can update subscription plans
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can update subscription plans"
        )

    plan_uuid = validate_uuid(plan_id, "plan ID")

    # Check if plan exists
    plan = await db.execute(
        select(SubscriptionPlan).where(SubscriptionPlan.id == plan_uuid)
    )
    plan = plan.scalar_one_or_none()

    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subscription plan not found"
        )

    # Check if plan code is being changed and if it conflicts with existing
    if plan_data.plan_code and plan_data.plan_code != plan.plan_code:
        existing_plan = await db.execute(
            select(SubscriptionPlan).where(
                and_(
                    SubscriptionPlan.plan_code == plan_data.plan_code,
                    SubscriptionPlan.id != plan_uuid
                )
            )
        )
        if existing_plan.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Plan with code '{plan_data.plan_code}' already exists"
            )

    # Update plan fields
    update_data = plan_data.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(plan, field, value)

    plan.updated_at = datetime.utcnow()
    plan.updated_by = user.id

    await db.commit()
    await db.refresh(plan)

    return plan


@router.delete("/{plan_id}")
async def delete_subscription_plan(
    plan_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> dict:
    """Delete subscription plan (soft delete)"""
    user = await get_current_user_required(request)

    # Only admins can delete subscription plans
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can delete subscription plans"
        )

    plan_uuid = validate_uuid(plan_id, "plan ID")

    # Check if plan exists
    plan = await db.execute(
        select(SubscriptionPlan).where(SubscriptionPlan.id == plan_uuid)
    )
    plan = plan.scalar_one_or_none()

    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subscription plan not found"
        )

    # Soft delete
    plan.deleted_at = datetime.utcnow()
    plan.is_active = False

    await db.commit()

    return {"message": "Subscription plan deleted successfully"}
