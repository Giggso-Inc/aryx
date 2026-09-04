"""
POST /zoho/invoices/companyInvoiceDetails   fetch_company_invoice_details
(mounted at /api/v1/payment-gateway)
"""

import logging
import uuid

from fastapi import APIRouter, HTTPException, status, Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.schemas.common import SuccessResponse, CompanySubscriptionDetailsRequest, CompanyInvoiceDetailsResponse

from .helpers import _fetch_invoice_details_for_company

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/zoho/invoices/companyInvoiceDetails", response_model=SuccessResponse[CompanyInvoiceDetailsResponse])
async def fetch_company_invoice_details(
    request_data: CompanySubscriptionDetailsRequest,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> SuccessResponse[CompanyInvoiceDetailsResponse]:
    """
    Fetch invoice details for a company (same structure as fetchCompanySubscriptionDetails invoice section).

    Returns invoice list and total cost. Any authenticated user in the company can access.
    """
    try:
        user = await get_current_user_required(request)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unauthorized"
            )
        company_id = request_data.companyId
        # Validate companyId is a valid UUID to avoid DB errors
        try:
            uuid.UUID(company_id)
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid companyId format"
            )
        if str(user.company_id) != str(company_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User does not belong to the requested company"
            )
        invoice_details, total_cost = await _fetch_invoice_details_for_company(db, company_id)
        response_data = CompanyInvoiceDetailsResponse(
            invoiceDetails=invoice_details,
            totalCost=str(total_cost) if total_cost > 0 else None
        )
        return SuccessResponse(
            success=True,
            data=response_data,
            message="OK",
            code=status.HTTP_200_OK
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Exception at fetch company invoice details: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}"
        )
