"""
Subscription Plans routes for CRUD operations

Author: Pranhav Vimalbalaji
Date: 2025-01-27
Version: 1.0.0
"""

from typing import List, Optional
from fastapi import APIRouter, HTTPException, status, Request, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, update, delete
from datetime import datetime
import uuid

from app.core.database import get_db
from app.core.auth import generate_channel_id
from app.middleware.auth_middleware import get_current_user_required
from app.models.user import User
from app.models.subscription_plan import SubscriptionPlan
from app.schemas.subscription_plan import (
    SubscriptionPlanCreate,
    SubscriptionPlanUpdate,
    SubscriptionPlanResponse,
    SubscriptionPlanList,
    SubscriptionPlanFilter
)

router = APIRouter()


def validate_uuid(uuid_string: str, field_name: str = "ID") -> uuid.UUID:
    """Validate and return UUID from string, or raise HTTPException if invalid"""
    try:
        return uuid.UUID(uuid_string)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid {field_name} format. Must be a valid UUID."
        )


@router.post("/", response_model=SubscriptionPlanResponse)
async def create_subscription_plan(
    plan_data: SubscriptionPlanCreate,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
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
):
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


@router.get("/{plan_id}", response_model=SubscriptionPlanResponse)
async def get_subscription_plan(
    plan_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
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
):
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
):
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


@router.get("/active/plans", response_model=List[SubscriptionPlanResponse])
async def get_active_plans(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Get all active subscription plans"""
    user = await get_current_user_required(request)
    
    result = await db.execute(
        select(SubscriptionPlan)
        .where(SubscriptionPlan.is_active == True)
        .order_by(SubscriptionPlan.sort_order.asc())
    )
    plans = result.scalars().all()
    
    return plans
