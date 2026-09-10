"""
Invoice-ownership verification + PDF download helpers for download_invoice
(invoice_download.py). Split out of that ~145-line handler so the
orchestrator can stay small; see invoice_download.py's module docstring for
the split rationale.

Both helpers take an already-resolved `zoho_service_instance` (rather than
calling get_zoho_service themselves) because
tests/test_payment_gateway_characterization.py patches get_zoho_service on
`app.routes.payment_gateway.invoice_download`, not on this module.

Documented pre-existing bug (characterized as-is, NOT fixed): the
ownership-check HTTPException(403) raised inside verify_invoice_ownership's
try-block is caught by that same block's `except Exception`, logged as a
warning, and swallowed — so the download proceeds even when the invoice
does not belong to the customer's invoice list. See
tests/test_payment_gateway_characterization.py::TestDownloadInvoice::
test_ownership_check_403_is_swallowed_bug.
"""

import logging

from fastapi import HTTPException, status
from fastapi.responses import Response

logger = logging.getLogger(__name__)


async def verify_invoice_ownership(zoho_service_instance, subscription, invoice_id: str) -> None:
    """Best-effort check that invoice_id belongs to the subscription's Zoho
    customer. Any failure (including a deliberate "not found" 403) is
    logged and swallowed, letting the download proceed — this is the
    documented pre-existing bug above, preserved as-is."""
    if subscription and subscription.zoho_customer_id:
        try:
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


async def download_invoice_pdf_response(zoho_service_instance, invoice_id: str) -> Response:
    """Download the invoice PDF from Zoho and wrap it as a downloadable
    Response."""
    try:
        pdf_content = await zoho_service_instance.download_invoice_pdf(invoice_id)

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
