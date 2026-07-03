"""
Subscriptions routes for CRUD operations and company plan management

Author: Pranhav Vimalbalaji
Date: 2025-01-27
Version: 1.0.0
"""

from typing import List, Optional
from fastapi import APIRouter, HTTPException, status, Request, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, update, delete
from datetime import datetime, timedelta, timezone
import uuid

from app.core.database import get_db
from app.core.auth import generate_channel_id
from app.middleware.auth_middleware import get_current_user_required
from app.models.user import User
from app.models.subscription import Subscription
from app.models.subscription_plan import SubscriptionPlan
from app.models.company import Company
from app.schemas.subscription import (
    SubscriptionCreate,
    SubscriptionUpdate,
    SubscriptionResponse,
    SubscriptionList,
    SubscriptionFilter,
    CompanyCurrentPlanResponse
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


@router.post("/", response_model=SubscriptionResponse)
async def create_subscription(
    subscription_data: SubscriptionCreate,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Create a new subscription for a company"""
    user = await get_current_user_required(request, db)
    
    # Only admins can create subscriptions
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can create subscriptions"
        )
    
    # Validate company exists
    company = await db.execute(
        select(Company).where(Company.id == subscription_data.company_id)
    )
    company = company.scalar_one_or_none()
    
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company not found"
        )
    
    # Validate plan exists
    plan = await db.execute(
        select(SubscriptionPlan).where(SubscriptionPlan.id == subscription_data.plan_id)
    )
    plan = plan.scalar_one_or_none()
    
    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subscription plan not found"
        )
    
    # Check if company already has an active subscription to this plan
    existing_subscription = await db.execute(
        select(Subscription).where(
            and_(
                Subscription.company_id == subscription_data.company_id,
                Subscription.plan_id == subscription_data.plan_id,
                Subscription.status.in_(["active", "trial"])
            )
        )
    )
    if existing_subscription.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Company already has an active subscription to this plan"
        )
    
    # Create new subscription
    subscription = Subscription(
        id=generate_channel_id(),  # Reuse the generator for UUID
        company_id=subscription_data.company_id,
        plan_id=subscription_data.plan_id,
        status=subscription_data.status,
        subscription_status=subscription_data.subscription_status,
        amount=subscription_data.amount,
        currency_code=subscription_data.currency_code,
        billing_cycle=subscription_data.billing_cycle,
        auto_collect=subscription_data.auto_collect,
        current_period_start=subscription_data.current_period_start,
        current_period_end=subscription_data.current_period_end,
        next_billing_date=subscription_data.next_billing_date,
        zoho_trial_end=subscription_data.zoho_trial_end,
        zoho_cancel_at_period_end=subscription_data.zoho_cancel_at_period_end,
        usage_limits=subscription_data.usage_limits,
        zoho_subscription_id=subscription_data.zoho_subscription_id,
        zoho_customer_id=subscription_data.zoho_customer_id,
        zoho_hosted_page_id=subscription_data.zoho_hosted_page_id,
        zoho_invoice_id=subscription_data.zoho_invoice_id,
        zoho_payment_id=subscription_data.zoho_payment_id,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc)
    )
    
    db.add(subscription)
    await db.commit()
    await db.refresh(subscription)
    
    return subscription


@router.get("/", response_model=SubscriptionList)
async def list_subscriptions(
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    company_id: Optional[str] = None,
    plan_id: Optional[str] = None,
    status: Optional[str] = None,
    subscription_status: Optional[str] = None,
    min_amount: Optional[float] = None,
    max_amount: Optional[float] = None,
    billing_cycle: Optional[str] = None,
    sort_by: Optional[str] = Query("created_at", description="Sort by: created_at, amount, current_period_end"),
    sort_order: Optional[str] = Query("desc", description="Sort order: asc or desc")
):
    """List subscriptions with filtering and pagination"""
    user = await get_current_user_required(request, db)
    
    # Only admins can list all subscriptions
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can list all subscriptions"
        )
    
    # Build base query
    query = select(Subscription)
    
    # Apply filters
    filters = []
    if company_id:
        company_uuid = validate_uuid(company_id, "company ID")
        filters.append(Subscription.company_id == company_uuid)
    if plan_id:
        plan_uuid = validate_uuid(plan_id, "plan ID")
        filters.append(Subscription.plan_id == plan_uuid)
    if status:
        filters.append(Subscription.status == status.lower())
    if subscription_status:
        filters.append(Subscription.subscription_status == subscription_status.lower())
    if min_amount is not None:
        filters.append(Subscription.amount >= min_amount)
    if max_amount is not None:
        filters.append(Subscription.amount <= max_amount)
    if billing_cycle:
        filters.append(Subscription.billing_cycle == billing_cycle)
    
    if filters:
        query = query.where(and_(*filters))
    
    # Apply sorting
    if sort_by == "amount":
        if sort_order.lower() == "asc":
            query = query.order_by(Subscription.amount.asc())
        else:
            query = query.order_by(Subscription.amount.desc())
    elif sort_by == "current_period_end":
        if sort_order.lower() == "asc":
            query = query.order_by(Subscription.current_period_end.asc())
        else:
            query = query.order_by(Subscription.current_period_end.desc())
    else:  # Default: sort by created_at
        if sort_order.lower() == "asc":
            query = query.order_by(Subscription.created_at.asc())
        else:
            query = query.order_by(Subscription.created_at.desc())
    
    # Get total count
    count_query = select(func.count(Subscription.id))
    if filters:
        count_query = count_query.where(and_(*filters))
    count_result = await db.execute(count_query)
    total = count_result.scalar()
    
    # Apply pagination
    offset = (page - 1) * size
    query = query.offset(offset).limit(size)
    
    # Execute query
    result = await db.execute(query)
    subscriptions = result.scalars().all()
    
    return SubscriptionList(
        subscriptions=subscriptions,
        total=total,
        page=page,
        size=size
    )


@router.get("/{subscription_id}", response_model=SubscriptionResponse)
async def get_subscription(
    subscription_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Get subscription by ID"""
    user = await get_current_user_required(request, db)
    
    subscription_uuid = validate_uuid(subscription_id, "subscription ID")
    
    subscription = await db.execute(
        select(Subscription).where(Subscription.id == subscription_uuid)
    )
    subscription = subscription.scalar_one_or_none()
    
    if not subscription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subscription not found"
        )
    
    # Only admins or company members can view subscription
    if not user.is_admin and str(user.company_id) != str(subscription.company_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to subscription"
        )
    
    return subscription


@router.put("/{subscription_id}", response_model=SubscriptionResponse)
async def update_subscription(
    subscription_id: str,
    subscription_data: SubscriptionUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Update subscription"""
    user = await get_current_user_required(request, db)
    
    # Only admins can update subscriptions
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can update subscriptions"
        )
    
    subscription_uuid = validate_uuid(subscription_id, "subscription ID")
    
    # Check if subscription exists
    subscription = await db.execute(
        select(Subscription).where(Subscription.id == subscription_uuid)
    )
    subscription = subscription.scalar_one_or_none()
    
    if not subscription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subscription not found"
        )
    
    # Update subscription fields
    update_data = subscription_data.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(subscription, field, value)
    
    subscription.updated_at = datetime.now(timezone.utc)
    
    await db.commit()
    await db.refresh(subscription)
    
    return subscription


@router.delete("/{subscription_id}")
async def delete_subscription(
    subscription_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Delete subscription (soft delete)"""
    user = await get_current_user_required(request, db)
    
    # Only admins can delete subscriptions
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can delete subscriptions"
        )
    
    subscription_uuid = validate_uuid(subscription_id, "subscription ID")
    
    # Check if subscription exists
    subscription = await db.execute(
        select(Subscription).where(Subscription.id == subscription_uuid)
    )
    subscription = subscription.scalar_one_or_none()
    
    if not subscription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subscription not found"
        )
    
    # Soft delete
    subscription.deleted_at = datetime.now(timezone.utc)
    subscription.status = "inactive"
    subscription.subscription_status = "inactive"
    
    
    await db.commit()
    
    return {"message": "Subscription deleted successfully"}


@router.get("/company/my/current-plan", response_model=CompanyCurrentPlanResponse)
async def get_my_company_current_plan(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Get current plan details for the authenticated user's company"""
    user = await get_current_user_required(request, db)
    
    # Check if user has a company_id
    if not user.company_id:
        # Return default free plan info for users without company
        return CompanyCurrentPlanResponse(
            plan_name="Free Plan",
            plan_code="free",
            billing_cycle="N/A",
            cost=0.00,
            currency_code="USD",
            next_renewal=datetime.now(timezone.utc) + timedelta(days=30),
            status="active",
            features={"max_users": 10, "max_workspaces": 5, "max_storage_gb": 1},
            current_period_start=datetime.now(timezone.utc),
            current_period_end=datetime.now(timezone.utc) + timedelta(days=30),
            is_trial=False,
            trial_end=None
        )
    
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
        return CompanyCurrentPlanResponse(
            plan_name="Free Plan",
            plan_code="free",
            billing_cycle="N/A",
            cost=0.00,
            currency_code="USD",
            next_renewal=datetime.now(timezone.utc) + timedelta(days=30),
            status="active",
            features={"max_users": 10, "max_workspaces": 5, "max_storage_gb": 1},
            current_period_start=datetime.now(timezone.utc),
            current_period_end=datetime.now(timezone.utc) + timedelta(days=30),
            is_trial=False,
            trial_end=None
        )
    
    subscription, plan = subscription_data
    
    # Determine if currently in trial
    is_trial = subscription.status == "trial"
    trial_end = subscription.zoho_trial_end if is_trial else None
    
    # Calculate next renewal date
    if subscription.next_billing_date:
        next_renewal = subscription.next_billing_date
    else:
        # Estimate based on billing cycle
        if subscription.billing_cycle.lower() == "monthly":
            next_renewal = subscription.current_period_end
        elif subscription.billing_cycle.lower() == "yearly":
            next_renewal = subscription.current_period_end
        else:
            next_renewal = subscription.current_period_end
    
    return CompanyCurrentPlanResponse(
        plan_name=plan.name,
        plan_code=plan.plan_code,
        billing_cycle=subscription.billing_cycle,
        cost=subscription.amount,
        currency_code=subscription.currency_code,
        next_renewal=next_renewal,
        status=subscription.status,
        features=plan.features,
        current_period_start=subscription.current_period_start,
        current_period_end=subscription.current_period_end,
        is_trial=is_trial,
        trial_end=trial_end
    )


@router.get("/company/{company_id}/current-plan", response_model=CompanyCurrentPlanResponse)
async def get_company_current_plan(
    company_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Get current plan details for a company"""
    user = await get_current_user_required(request, db)
    
    company_uuid = validate_uuid(company_id, "company ID")
    
    # Check if company exists
    company = await db.execute(
        select(Company).where(Company.id == company_uuid)
    )
    company = company.scalar_one_or_none()
    
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company not found"
        )
    
    # Only admins or company members can view company plan
    if not user.is_admin and str(user.company_id) != str(company_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to company plan"
        )
    
    # Get current active subscription
    subscription = await db.execute(
        select(Subscription, SubscriptionPlan).join(
            SubscriptionPlan, Subscription.plan_id == SubscriptionPlan.id
        ).where(
            and_(
                Subscription.company_id == company_uuid,
                Subscription.status.in_(["active", "trial"]),
                Subscription.deleted_at.is_(None)
            )
        ).order_by(Subscription.created_at.desc())
    )
    subscription_data = subscription.first()
    
    if not subscription_data:
        # Return default free plan info
        return CompanyCurrentPlanResponse(
            plan_name="Free Plan",
            plan_code="free",
            billing_cycle="N/A",
            cost=0.00,
            currency_code="USD",
            next_renewal=datetime.now(timezone.utc) + timedelta(days=30),
            status="active",
            features={"max_users": 10, "max_workspaces": 5, "max_storage_gb": 1},
            current_period_start=datetime.now(timezone.utc),
            current_period_end=datetime.now(timezone.utc) + timedelta(days=30),
            is_trial=False,
            trial_end=None
        )
    
    subscription, plan = subscription_data
    
    # Determine if currently in trial
    is_trial = subscription.status == "trial"
    trial_end = subscription.zoho_trial_end if is_trial else None
    
    # Calculate next renewal date
    if subscription.next_billing_date:
        next_renewal = subscription.next_billing_date
    else:
        # Estimate based on billing cycle
        if subscription.billing_cycle.lower() == "monthly":
            next_renewal = subscription.current_period_end
        elif subscription.billing_cycle.lower() == "yearly":
            next_renewal = subscription.current_period_end
        else:
            next_renewal = subscription.current_period_end
    
    return CompanyCurrentPlanResponse(
        plan_name=plan.name,
        plan_code=plan.plan_code,
        billing_cycle=subscription.billing_cycle,
        cost=subscription.amount,
        currency_code=subscription.currency_code,
        next_renewal=next_renewal,
        status=subscription.status,
        features=plan.features,
        current_period_start=subscription.current_period_start,
        current_period_end=subscription.current_period_end,
        is_trial=is_trial,
        trial_end=trial_end
    )



