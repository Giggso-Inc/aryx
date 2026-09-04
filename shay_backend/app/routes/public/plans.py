"""Subscription plan listing for onboarding: GET /fetchPlans."""

from typing import List, Optional
from fastapi import APIRouter, HTTPException, status, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.models.subscription_plan import SubscriptionPlan
from app.schemas.subscription_plan import SubscriptionPlanNodeResponse
from app.schemas.common import SuccessResponse

router = APIRouter()


@router.get("/fetchPlans", response_model=SuccessResponse[List[SubscriptionPlanNodeResponse]])
async def fetch_plans(
    platform_name: Optional[str] = Query(None, description="Filter plans by platform name (e.g., 'prism7', 'accsell', 'zaptag'). If not provided, returns all plans."),
    db: AsyncSession = Depends(get_db)
) -> SuccessResponse[List[SubscriptionPlanNodeResponse]]:
    """
    Fetches all available subscription plans for onboarding.

    Called during the onboarding flow to display plan options.
    If platform_name is provided, filters plans by that platform.
    If platform_name is null/not provided, returns all active plans.
    """
    try:
        # Build query for active subscription plans
        query = select(SubscriptionPlan).where(SubscriptionPlan.is_active == True)

        # Filter by platform_name if provided
        if platform_name:
            query = query.where(SubscriptionPlan.platform_name == platform_name)

        # Execute query
        result = await db.execute(query)
        plans = result.scalars().all()

        # Clean and validate plans before returning
        cleaned_plans = []
        for plan in plans:
            try:
                # Create a cleaned plan object with Node.js format
                cleaned_plan = {
                    "name": plan.name,
                    "planCode": plan.plan_code,
                    "description": plan.description,
                    "monthlyPrice": str(plan.monthly_price),
                    "planCycles": max(1, plan.plan_cycles) if plan.plan_cycles is not None else 1,
                    "features": plan.features or [],
                    "isActive": plan.is_active,
                    "sortOrder": plan.sort_order or 0,
                    "createdAt": plan.created_at.isoformat() if plan.created_at else None,
                    "updatedAt": plan.updated_at.isoformat() if plan.updated_at else None,
                    "zohoPlanId": plan.zoho_plan_id,
                    "zohoProductId": plan.zoho_product_id,
                    "intervalCount": max(1, plan.interval_count) if plan.interval_count is not None else 1,
                    "deletedAt": None,  # We don't have this field
                    "zohoPlanCode": plan.zoho_plan_code,
                    "zohoProductCode": plan.zoho_product_code,
                    "zohoBillingCycle": plan.zoho_billing_cycle,
                    "updatedBy": None,  # We don't have this field
                    "intervalUnit": plan.interval_unit or "months",
                    "interval": max(1, plan.interval) if plan.interval is not None else 1,
                    "id": str(plan.id),
                    "createdBy": None,  # We don't have this field
                    "subscriberCount": "0",  # We don't track this yet
                    "createdByEmail": "System",  # Default value
                    "createdByRole": "System",  # Default value
                    "createdById": "00000000-0000-0000-0000-000000000000"  # Default value
                }

                # Validate the cleaned plan
                validated_plan = SubscriptionPlanNodeResponse(**cleaned_plan)
                cleaned_plans.append(validated_plan)

            except Exception as plan_error:
                # Log the error but continue with other plans
                print(f"Warning: Skipping plan {plan.id} due to validation error: {plan_error}")
                continue

        return SuccessResponse(
            success=True,
            data=cleaned_plans,
            message="Plans fetched successfully",
            code=status.HTTP_200_OK
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch plans: {str(e)}"
        )
