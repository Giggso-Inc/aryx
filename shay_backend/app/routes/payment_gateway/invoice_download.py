"""
GET /zoho/invoices/{invoice_id}/download   download_invoice
(mounted at /api/v1/payment-gateway)
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, status, Request, Depends, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.company import Company
from app.models.subscription import Subscription
from app.services.zoho_service import get_zoho_service

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/zoho/invoices/{invoice_id}/download")
async def download_invoice(
    invoice_id: str,
    platform_name: Optional[str] = Query(None, description="Platform name (e.g., 'prism7')"),
    request: Request = None,
    db: AsyncSession = Depends(get_db)
) -> Response:
    """
    Download invoice PDF from Zoho.

    This endpoint downloads the invoice PDF file from Zoho and returns it as a downloadable file.
    Only company admins can download invoices for their company.

    Args:
        invoice_id: The Zoho invoice ID
        platform_name: Platform name (e.g., 'prism7'). If 'prism7', uses PRISM Zoho configuration.

    Returns:
        PDF file as binary response with appropriate headers
    """
    try:
        # Log request details for debugging
        auth_header = request.headers.get("Authorization") if request else None
        user_id_from_state = getattr(request.state, "user_id", None) if request else None

        logger.info(f"🔍 Invoice download request - invoice_id: {invoice_id}, platform_name: {platform_name}")
        logger.info(f"🔍 Auth header present: {bool(auth_header)}")
        logger.info(f"🔍 User ID from request.state: {user_id_from_state}")

        # Get current user for authentication
        if not request:
            logger.error("❌ Request object is None")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Request object not found"
            )

        # Check if user_id is in request state (set by AuthMiddleware)
        if not user_id_from_state:
            logger.error("❌ No user_id in request.state - Authentication header missing or invalid")
            logger.error(f"❌ Authorization header: {auth_header[:50] + '...' if auth_header and len(auth_header) > 50 else auth_header}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required - Please provide a valid Bearer token in the Authorization header",
                headers={"WWW-Authenticate": "Bearer"}
            )

        try:
            user = await get_current_user_required(request, db)
            logger.info(f"✅ User authenticated: {user.id if user else 'None'}")
        except HTTPException as auth_error:
            logger.error(f"❌ Authentication failed: {auth_error.detail}, status: {auth_error.status_code}")
            raise
        except Exception as auth_ex:
            logger.error(f"❌ Authentication error: {str(auth_ex)}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Authentication failed: {str(auth_ex)}"
            )

        if not user:
            logger.error("❌ User is None after authentication")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unauthorized - User not found"
            )

        # Verify user is company admin
        if user.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only company admins can download invoices"
            )

        # Get company subscription to verify invoice belongs to user's company
        company_result = await db.execute(
            select(Company).where(Company.id == user.company_id)
        )
        company = company_result.scalar_one_or_none()

        if not company:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Company not found"
            )

        # Get subscription to verify customer_id matches
        subscription_result = await db.execute(
            select(Subscription)
            .where(Subscription.company_id == company.id)
            .order_by(Subscription.created_at.desc())
            .limit(1)
        )
        subscription = subscription_result.scalar_one_or_none()

        # Default to 'prism7' if platform_name is not provided (since PRISM credentials are configured)
        effective_platform_name = platform_name if platform_name else 'prism7'

        if subscription and subscription.zoho_customer_id:
            # Verify invoice belongs to this customer by fetching invoice details
            zoho_service_instance = get_zoho_service(effective_platform_name)
            try:
                # Get invoice details to verify it belongs to the customer
                invoices = await zoho_service_instance.get_customer_invoices(subscription.zoho_customer_id)
                invoice_found = any(inv.get('invoice_id') == invoice_id for inv in invoices)

                if not invoice_found:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Invoice does not belong to your company"
                    )
            except Exception as verify_error:
                logger.warning(f"Could not verify invoice ownership: {verify_error}")
                # Continue with download attempt - Zoho API will handle authorization

        # Get appropriate Zoho service instance
        zoho_service_instance = get_zoho_service(effective_platform_name)

        # Download invoice PDF from Zoho
        try:
            pdf_content = await zoho_service_instance.download_invoice_pdf(invoice_id)

            # Return PDF as downloadable file
            return Response(
                content=pdf_content,
                media_type="application/pdf",
                headers={
                    "Content-Disposition": f'attachment; filename="invoice_{invoice_id}.pdf"',
                    "Content-Type": "application/pdf"
                }
            )

        except Exception as zoho_error:
            logger.error(f"Zoho API error downloading invoice: {zoho_error}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to download invoice: {str(zoho_error)}"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Exception at download invoice: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}"
        )
