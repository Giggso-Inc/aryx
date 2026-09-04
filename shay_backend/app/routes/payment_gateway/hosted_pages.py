"""
Zoho hosted-page endpoints (mounted at /api/v1/payment-gateway):
  POST /zoho/subscriptions/hostedPage/create           create_zoho_hosted_page
  GET  /zoho/subscriptions/fetchByHostedId/{hostedPageId}  fetch_by_hosted_id
  PUT  /zoho/subscriptions/hostedPage/update           update_subscription_hosted_page

Stated exception: create_zoho_hosted_page is ~155 lines on its own (over the
~150-line-per-file target for the whole module) because it has two full,
independent response-building branches (real Zoho response vs. fallback/mock
response when the Zoho API call fails) that are part of one atomic
request/response flow. Splitting the branches into separate files would
fragment a single try/except's logic without isolating any independently
reusable concern.
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timedelta
import uuid

from app.core.database import get_db
from app.core.config import settings
from app.middleware.auth_middleware import get_current_user_required
from app.models.company import Company
from app.models.subscription_plan import SubscriptionPlan
from app.models.subscription import Subscription
from app.schemas.common import SuccessResponse, ZohoHostedPageRequest, ZohoHostedPageResponse, SubscriptionUpdateRequest
from app.services.zoho_service import get_zoho_service
from fastapi import Depends

import logging

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/zoho/subscriptions/hostedPage/create", response_model=SuccessResponse[ZohoHostedPageResponse])
async def create_zoho_hosted_page(
    request_data: ZohoHostedPageRequest,
    db: AsyncSession = Depends(get_db)
) -> SuccessResponse[ZohoHostedPageResponse]:
    """
    Creates a Zoho hosted payment page for subscription.

    This endpoint uses real Zoho API integration.
    """
    try:
        # Extract plan information from request
        plan_name = request_data.plan.get("name")
        plan_code = request_data.plan.get("planCode")

        # Find the plan in database
        plan_result = await db.execute(
            select(SubscriptionPlan).where(
                SubscriptionPlan.name == plan_name,
                SubscriptionPlan.plan_code == plan_code,
                SubscriptionPlan.is_active == True
            )
        )
        plan = plan_result.scalar_one_or_none()

        if not plan:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Plan not found"
            )

        # Extract customer information
        customer_data = request_data.customer
        company_name = customer_data.get("companyName")
        customer_email = customer_data.get("email")

        # Find the company
        company_result = await db.execute(
            select(Company).where(Company.name == company_name)
        )
        company = company_result.scalar_one_or_none()

        if not company:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Company not found"
            )

        # Check for existing Zoho customer ID on company's latest subscription (use existing customer in Zoho when present)
        subscription_result = await db.execute(
            select(Subscription)
            .where(Subscription.company_id == company.id)
            .order_by(Subscription.created_at.desc())
            .limit(1)
        )
        existing_subscription = subscription_result.scalar_one_or_none()
        zoho_customer_id = existing_subscription.zoho_customer_id if existing_subscription else None

        # Create hosted page using Zoho service
        try:
            # Get platform_name from request (if provided)
            platform_name = request_data.platform_name if hasattr(request_data, 'platform_name') else None

            # Get appropriate Zoho service instance based on platform_name
            zoho_service_instance = get_zoho_service(platform_name)

            # Prepare subscription data: send zoho_customer_id when we have it (existing customer), else customer object for new customer
            subscription_data = {
                "planName": plan.name,
                "planCode": plan.plan_code,
                "planDescription": plan.description,
                "redirectUrl": request_data.redirectUrl,
                "autoCollect": getattr(request_data, "autoCollect", True),
            }
            if zoho_customer_id:
                subscription_data["zoho_customer_id"] = zoho_customer_id
            else:
                subscription_data["customerName"] = customer_data.get("displayName", customer_data.get("companyName", "Customer"))
                subscription_data["customerEmail"] = customer_data.get("email")
                subscription_data["companyName"] = customer_data.get("companyName")
                subscription_data["companyDomain"] = customer_data.get("website", "")

            zoho_response = await zoho_service_instance.create_hosted_page(subscription_data)

            # Extract hosted page details from Zoho response
            hosted_page_id = zoho_response.get("hostedPageId")
            hosted_page_url = zoho_response.get("hostedPageUrl")

            if not hosted_page_id or not hosted_page_url:
                raise Exception("Invalid response from Zoho API")

            # Create hosted page data
            hosted_page_data = ZohoHostedPageResponse(
                hostedPageId=hosted_page_id,
                url=hosted_page_url,
                planId=str(plan.id),
                planName=plan.name,
                amount=float(plan.monthly_price),
                companyId=str(company.id),
                companyName=company.name,
                expiresAt=(datetime.utcnow() + timedelta(hours=24)).isoformat()
            )

            return SuccessResponse(
                success=True,
                data=hosted_page_data,
                message="Zoho hosted payment page created successfully",
                code=status.HTTP_200_OK
            )

        except Exception as zoho_error:
            # Fallback to mock response if Zoho API fails
            print(f"Zoho API error: {zoho_error}")
            hosted_page_id = str(uuid.uuid4())

            # Use appropriate base URL; no platform_name or unknown value → default (previous flow unchanged)
            if platform_name:
                pn = platform_name.lower()
                if pn == "prism7":
                    base_url = settings.PRISM_ZOHO_BASE_URL
                elif pn == "accsell":
                    base_url = settings.SHAY_ZOHO_BASE_URL
                elif pn == "zaptag":
                    base_url = settings.ZAPTAG_ZOHO_BASE_URL
                else:
                    base_url = settings.ZOHO_BASE_URL
            else:
                base_url = settings.ZOHO_BASE_URL

            hosted_page_data = ZohoHostedPageResponse(
                hostedPageId=hosted_page_id,
                url=f"{base_url}/hosted-page/{hosted_page_id}",
                planId=str(plan.id),
                planName=plan.name,
                amount=float(plan.monthly_price),
                companyId=str(company.id),
                companyName=company.name,
                expiresAt=(datetime.utcnow() + timedelta(hours=24)).isoformat()
            )

            return SuccessResponse(
                success=True,
                data=hosted_page_data,
                message="Hosted payment page created (fallback mode)",
                code=status.HTTP_200_OK
            )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create hosted page: {str(e)}"
        )


@router.get("/zoho/subscriptions/fetchByHostedId/{hostedPageId}", response_model=SuccessResponse[dict])
async def fetch_by_hosted_id(
    hostedPageId: str,
    request: Request,
    platform_name: Optional[str] = None
) -> SuccessResponse[dict]:
    """
    Retrieve hosted page data by hosted page ID.

    This endpoint fetches hosted page information from Zoho.

    Args:
        platform_name: Platform name (e.g., 'prism7', 'accsell', 'zaptag'). If one of these, uses that platform's Zoho configuration.
    """
    try:
        # Get current user for authentication
        user = await get_current_user_required(request)

        # Verify user is company admin
        if user.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only company admins can access hosted page data"
            )

        # Get appropriate Zoho service instance based on platform_name (for future Zoho API calls)
        zoho_service_instance = get_zoho_service(platform_name)

        # For now, return a placeholder response as per Node.js implementation
        # In a real implementation, this would fetch data from Zoho API using zoho_service_instance
        base_url = zoho_service_instance.base_url.replace('/billing/v1', '') if zoho_service_instance.base_url else 'https://zoho.com'
        hosted_page_data = {
            "hostedPageId": hostedPageId,
            "status": "active",
            "url": f"{base_url}/hosted-page/{hostedPageId}"
        }

        return SuccessResponse(
            success=True,
            data=hosted_page_data,
            message="Hosted page retrieved successfully",
            code=status.HTTP_200_OK
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve hosted page: {str(e)}"
        )


@router.put("/zoho/subscriptions/hostedPage/update", response_model=SuccessResponse[dict])
async def update_subscription_hosted_page(
    subscription_request: SubscriptionUpdateRequest,
    request: Request
) -> SuccessResponse[dict]:
    """
    Create a hosted page for updating a subscription.

    This endpoint creates a Zoho hosted payment page that allows customers
    to update their subscription (change plan, add addons, etc.).

    Reference: https://www.zoho.com/billing/api/v1/hosted-pages/#update-a-subscription
    """
    try:
        # Validate request
        if not subscription_request:
            return SuccessResponse(
                success=False,
                data=None,
                message="Subscription request is required",
                code=status.HTTP_400_BAD_REQUEST
            )

        # Get current user for authentication
        user = await get_current_user_required(request)

        # Verify user is company admin
        if user.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only company admins can update subscriptions"
            )

        # Get platform_name from request
        platform_name = subscription_request.platform_name

        # Get appropriate Zoho service instance based on platform_name
        zoho_service_instance = get_zoho_service(platform_name)

        # Convert Pydantic model to dict for service
        subscription_data = subscription_request.model_dump(exclude_none=True)

        # Call Zoho service to create update subscription hosted page
        try:
            zoho_response = await zoho_service_instance.update_subscription_hosted_page(subscription_data)

            if zoho_response and zoho_response.get('hostedPageId'):
                return SuccessResponse(
                    success=True,
                    data=zoho_response,
                    message="Hosted page for subscription update created successfully",
                    code=status.HTTP_200_OK
                )
            else:
                return SuccessResponse(
                    success=False,
                    data=None,
                    message="Failed to create hosted page for subscription update",
                    code=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

        except Exception as zoho_error:
            logger.error(f"Zoho API error: {zoho_error}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to create hosted page: {str(zoho_error)}"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Exception at update subscription hosted page: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}"
        )
