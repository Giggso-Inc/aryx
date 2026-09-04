"""
GET/PUT/DELETE /{subscription_id} — get, update, and (soft) delete a single
subscription.

Split from the original app/routes/subscriptions.py (Raven style-compliance
pass, see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2).
"""

from fastapi import APIRouter, HTTPException, status, Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.subscription import Subscription
from app.schemas.subscription import SubscriptionUpdate, SubscriptionResponse

from .helpers import validate_uuid

router = APIRouter()


@router.get("/{subscription_id}", response_model=SubscriptionResponse)
async def get_subscription(
    subscription_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> SubscriptionResponse:
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
) -> SubscriptionResponse:
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
) -> dict:
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
