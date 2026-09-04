"""Current company's subscription lookup: GET /mySubscription."""

from fastapi import APIRouter, HTTPException, status, Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.auth import decode_access_token
from app.models.subscription_plan import SubscriptionPlan
from app.models.subscription import Subscription
from app.schemas.subscription_plan import SubscriptionPlanNodeResponse
from app.schemas.common import SuccessResponse

router = APIRouter()


@router.get("/mySubscription", response_model=SuccessResponse[SubscriptionPlanNodeResponse])
async def get_my_subscription(
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> SuccessResponse[SubscriptionPlanNodeResponse]:
    """
    Get current company's subscription details.

    This endpoint extracts company ID from the JWT token in Authorization header.
    """
    try:
        # Get company ID from the JWT token in Authorization header
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authorization header with Bearer token is required"
            )

        # Extract token and decode to get company_id
        token = auth_header.split(" ")[1]
        try:
            token_data = decode_access_token(token)
            company_id = token_data.get("company_id")

            if not company_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Company ID not found in token"
                )
        except Exception as token_error:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid or expired token: {str(token_error)}"
            )

        # Get the company's latest subscription (regardless of status)
        subscription_result = await db.execute(
            select(Subscription).where(
                Subscription.company_id == company_id
            ).order_by(Subscription.created_at.desc()).limit(1)
        )
        subscription = subscription_result.scalar_one_or_none()

        if not subscription:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No subscription found"
            )

        # Get the subscription plan details
        plan_result = await db.execute(
            select(SubscriptionPlan).where(SubscriptionPlan.id == subscription.plan_id)
        )
        plan = plan_result.scalar_one_or_none()

        if not plan:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Subscription plan not found"
            )

        # Create response in Node.js format
        plan_data = {
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
            "deletedAt": None,
            "zohoPlanCode": plan.zoho_plan_code,
            "zohoProductCode": plan.zoho_product_code,
            "zohoBillingCycle": plan.zoho_billing_cycle,
            "updatedBy": None,
            "intervalUnit": plan.interval_unit or "months",
            "interval": max(1, plan.interval) if plan.interval is not None else 1,
            "id": str(plan.id),
            "createdBy": None,
            "subscriberCount": "0",
            "createdByEmail": "System",
            "createdByRole": "System",
            "createdById": "00000000-0000-0000-0000-000000000000",
            "zohoSubscriptionId": subscription.zoho_subscription_id,
            "subscriptionStatus": subscription.status,
            "endDate": subscription.current_period_end.isoformat() if subscription.current_period_end else None,
            "cancelAtPeriodEnd": subscription.zoho_cancel_at_period_end,
            "zohoCustomerId": subscription.zoho_customer_id  # Zoho customer ID
        }

        validated_plan = SubscriptionPlanNodeResponse(**plan_data)

        return SuccessResponse(
            success=True,
            data=validated_plan,
            message="Subscription details fetched successfully",
            code=status.HTTP_200_OK
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch subscription: {str(e)}"
        )
