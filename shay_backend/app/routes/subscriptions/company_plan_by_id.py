"""GET /company/{company_id}/current-plan — get_company_current_plan.

Split from the original company_plan.py (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Wave B4).
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.company import Company
from app.models.subscription import Subscription
from app.models.subscription_plan import SubscriptionPlan
from app.schemas.subscription import CompanyCurrentPlanResponse

from .company_plan_shared import default_free_plan_response, plan_response_from_subscription
from .helpers import validate_uuid

router = APIRouter()


@router.get("/company/{company_id}/current-plan", response_model=CompanyCurrentPlanResponse)
async def get_company_current_plan(
    company_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> CompanyCurrentPlanResponse:
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
        return default_free_plan_response()

    subscription, plan = subscription_data
    return plan_response_from_subscription(subscription, plan)
