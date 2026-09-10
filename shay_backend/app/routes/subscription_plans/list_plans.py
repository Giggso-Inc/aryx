"""
GET / -> list_subscription_plans.

Split from the original 327-line app/routes/subscription_plans.py (Raven
style-compliance pass, see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md,
wave B5).
"""

from typing import Optional

from fastapi import APIRouter, Request, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.subscription_plan import SubscriptionPlan
from app.schemas.subscription_plan import SubscriptionPlanList

router = APIRouter()


@router.get("/", response_model=SubscriptionPlanList)
async def list_subscription_plans(
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    search: Optional[str] = None,
    is_active: Optional[bool] = None,
    plan_code: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    interval_unit: Optional[str] = None,
    sort_by: Optional[str] = Query("sort_order", description="Sort by: sort_order, name, monthly_price, created_at"),
    sort_order: Optional[str] = Query("asc", description="Sort order: asc or desc")
) -> SubscriptionPlanList:
    """List subscription plans with filtering and pagination"""
    user = await get_current_user_required(request)

    # Build base query
    query = select(SubscriptionPlan)

    # Apply filters
    filters = []
    if is_active is not None:
        filters.append(SubscriptionPlan.is_active == is_active)
    if plan_code:
        filters.append(SubscriptionPlan.plan_code.ilike(f"%{plan_code}%"))
    if min_price is not None:
        filters.append(SubscriptionPlan.monthly_price >= min_price)
    if max_price is not None:
        filters.append(SubscriptionPlan.monthly_price <= max_price)
    if interval_unit:
        filters.append(SubscriptionPlan.interval_unit == interval_unit.lower())
    if search:
        filters.append(
            (SubscriptionPlan.name.ilike(f"%{search}%")) |
            (SubscriptionPlan.description.ilike(f"%{search}%"))
        )

    if filters:
        query = query.where(and_(*filters))

    # Apply sorting
    if sort_by == "name":
        if sort_order.lower() == "asc":
            query = query.order_by(SubscriptionPlan.name.asc())
        else:
            query = query.order_by(SubscriptionPlan.name.desc())
    elif sort_by == "monthly_price":
        if sort_order.lower() == "asc":
            query = query.order_by(SubscriptionPlan.monthly_price.asc())
        else:
            query = query.order_by(SubscriptionPlan.monthly_price.desc())
    elif sort_by == "created_at":
        if sort_order.lower() == "asc":
            query = query.order_by(SubscriptionPlan.created_at.asc())
        else:
            query = query.order_by(SubscriptionPlan.created_at.desc())
    else:  # Default: sort by sort_order
        if sort_order.lower() == "asc":
            query = query.order_by(SubscriptionPlan.sort_order.asc())
        else:
            query = query.order_by(SubscriptionPlan.sort_order.desc())

    # Get total count
    count_query = select(func.count(SubscriptionPlan.id))
    if filters:
        count_query = count_query.where(and_(*filters))
    count_result = await db.execute(count_query)
    total = count_result.scalar()

    # Apply pagination
    offset = (page - 1) * size
    query = query.offset(offset).limit(size)

    # Execute query
    result = await db.execute(query)
    plans = result.scalars().all()

    return SubscriptionPlanList(
        plans=plans,
        total=total,
        page=page,
        size=size
    )
