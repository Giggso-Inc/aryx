"""
GET / — list_subscriptions.

Split from the original app/routes/subscriptions.py (Raven style-compliance
pass, see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2).

STATED BUG (characterized, not fixed — see
tests/test_subscriptions_characterization.py::TestListSubscriptions):
the `status` query parameter below shadows the module-level
`from fastapi import status` import for the rest of this function's scope,
so the intended 403 branch for non-admins raises AttributeError (500)
instead. Preserved exactly as in the original file.
"""

from typing import Optional
from fastapi import APIRouter, HTTPException, status, Request, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.subscription import Subscription
from app.schemas.subscription import SubscriptionList

from .helpers import validate_uuid

router = APIRouter()


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
) -> SubscriptionList:
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
