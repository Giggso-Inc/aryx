"""
POST /zoho/subscriptions/fetchCompanySubscriptionDetails   fetch_company_subscription_details
(mounted at /api/v1/payment-gateway)

Thin orchestrator: authenticates/authorizes the request, then delegates to
sibling helper modules for DB lookups (subscription_details_lookup,
subscription_details_counts), Zoho invoice reconciliation
(subscription_details_zoho), and usage-statistics computation
(subscription_details_usage).
"""

import json
import logging

from fastapi import APIRouter, HTTPException, status, Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.common import (
    SuccessResponse,
    CompanySubscriptionDetailsRequest,
    CompanySubscriptionDetailsResponse,
)

from .helpers import _is_missing_table_error
from .subscription_details_auth import _authenticate_and_authorize
from .subscription_details_lookup import (
    _fetch_company,
    _fetch_active_subscription,
    _fetch_plan,
    _build_plan_summary,
)
from .subscription_details_counts import (
    _fetch_user_counts,
    _fetch_workspace_count,
    _fetch_channel_count,
    _fetch_ai_response_count,
    _fetch_storage_totals,
    _fetch_shared_inbox_count,
)
from .subscription_details_zoho import _fetch_invoice_details
from .subscription_details_usage import _calculate_usage_statistics

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/zoho/subscriptions/fetchCompanySubscriptionDetails", response_model=SuccessResponse[CompanySubscriptionDetailsResponse])
async def fetch_company_subscription_details(
    request_data: CompanySubscriptionDetailsRequest,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> SuccessResponse[CompanySubscriptionDetailsResponse]:
    """
    Fetch company subscription details.

    This endpoint returns comprehensive subscription information for a company,
    including plan details, user counts, channel counts, invoice details, etc.

    Only company admins can access this endpoint.
    """
    try:
        company_id = request_data.companyId
        await _authenticate_and_authorize(request, company_id)

        company = await _fetch_company(db, company_id)
        if not company:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Company not found"
            )

        subscription = await _fetch_active_subscription(db, company_id)
        if not subscription:
            return SuccessResponse(
                success=False,
                data=None,
                message="No subscription found for company",
                code=status.HTTP_404_NOT_FOUND
            )

        plan = await _fetch_plan(db, subscription.plan_id)
        if not plan:
            return SuccessResponse(
                success=False,
                data=None,
                message="Plan not found",
                code=status.HTTP_404_NOT_FOUND
            )

        response_data = _build_plan_summary(plan, subscription)

        admin_count, user_count = await _fetch_user_counts(db, company_id)
        response_data["userInfo"] = {"admin": admin_count, "users": user_count}

        response_data["companyGroupCount"] = await _fetch_workspace_count(db, company_id)

        channel_count = await _fetch_channel_count(db, company_id)
        response_data["companyChannelCount"] = channel_count

        response_data["aiResponseCount"] = await _fetch_ai_response_count(db, company_id)

        total_storage = await _fetch_storage_totals(db, company_id)
        response_data["storageCount"] = total_storage

        response_data["sharedInboxCount"] = await _fetch_shared_inbox_count(db, company_id)

        # Get metadata and addon details from subscription
        if subscription.usage_limits:
            if isinstance(subscription.usage_limits, dict):
                response_data["metadata"] = subscription.usage_limits
            elif isinstance(subscription.usage_limits, str):
                try:
                    response_data["metadata"] = json.loads(subscription.usage_limits)
                except:
                    response_data["metadata"] = None

        # Addon details - for now set to None (can be added later if stored)
        response_data["addonDetails"] = None

        invoice_details, total_cost = await _fetch_invoice_details(db, subscription, plan, company_id)
        response_data["invoiceDetails"] = invoice_details
        response_data["totalCost"] = str(total_cost) if total_cost > 0 else None

        response_data["usageStatistics"] = await _calculate_usage_statistics(
            db, plan, channel_count, total_storage, company_id
        )

        validated_response = CompanySubscriptionDetailsResponse(**response_data)

        return SuccessResponse(
            success=True,
            data=validated_response,
            message="Subscription details fetched successfully",
            code=status.HTTP_200_OK
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Exception at fetch company subscription details: %s", str(e))
        # Previous flow unchanged: only missing-table errors get generic message; all other errors keep str(e)
        detail = "Internal Server Error: Try Again Later" if _is_missing_table_error(e) else f"Internal server error: {str(e)}"
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=detail
        )
