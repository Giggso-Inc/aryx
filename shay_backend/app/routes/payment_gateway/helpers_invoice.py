"""
Zoho invoice fetch/reconciliation for a company's active subscription.

Extracted from helpers.py (Raven style compliance, wave B). Used by
invoice_details.py to build the companyInvoiceDetails response. All
Zoho/network errors are swallowed here exactly as in the original code
(logged as warnings, empty invoice list returned) so a Zoho outage never
fails the endpoint.
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.subscription import Subscription
from app.models.subscription_plan import SubscriptionPlan
from app.services.zoho_service import get_zoho_service

logger = logging.getLogger(__name__)


async def _fetch_invoice_details_for_company(db: AsyncSession, company_id: str) -> tuple:
    """
    Fetch invoice details from Zoho for the company's active subscription.
    Returns (invoice_details: list, total_cost: float). Uses same structure as fetchCompanySubscriptionDetails.
    company_id can be str or UUID; DB comparison accepts both.
    """
    invoice_details = []
    total_cost = 0.0
    # Get active subscription for company
    subscription_result = await db.execute(
        select(Subscription)
        .where(
            Subscription.company_id == company_id,
            Subscription.status == "active"
        )
        .order_by(Subscription.created_at.desc())
        .limit(1)
    )
    subscription = subscription_result.scalar_one_or_none()
    if not subscription or not subscription.zoho_customer_id:
        return invoice_details, total_cost
    # Get plan for fallback name/code
    plan_result = await db.execute(
        select(SubscriptionPlan).where(SubscriptionPlan.id == subscription.plan_id)
    )
    plan = plan_result.scalar_one_or_none()
    plan_name = plan.name if plan else None
    plan_code = plan.plan_code if plan else None
    try:
        zoho_service_instance = get_zoho_service("prism7")
        invoices = await zoho_service_instance.get_customer_invoices(subscription.zoho_customer_id)
        if not invoices:
            return invoice_details, total_cost
        for invoice in invoices:
            invoice_id = invoice.get("invoice_id")
            full_invoice_data = None
            invoice_name = None
            invoice_code = None
            try:
                full_invoice_data = await zoho_service_instance.get_invoice(invoice_id)
                invoice_items = full_invoice_data.get("invoice_items", [])
                if invoice_items:
                    first_item = invoice_items[0]
                    invoice_name = first_item.get("name")
                    invoice_code = first_item.get("code")
            except Exception as detail_error:
                logger.warning("Could not fetch full invoice details for %s: %s", invoice_id, detail_error)
            invoice_to_process = full_invoice_data if full_invoice_data else invoice
            subscription_plan_details = {
                "name": invoice_name if invoice_name else plan_name,
                "planCode": invoice_code if invoice_code else plan_code
            }
            invoice_data = {
                "invoice_id": invoice_id,
                "number": invoice_to_process.get("number") or invoice_to_process.get("invoice_number"),
                "status": invoice_to_process.get("status"),
                "invoice_date": invoice_to_process.get("invoice_date") or invoice_to_process.get("date"),
                "due_date": invoice_to_process.get("due_date"),
                "total": invoice_to_process.get("total"),
                "balance": invoice_to_process.get("balance"),
                "payment_made": invoice_to_process.get("payment_made"),
                "currency_code": invoice_to_process.get("currency_code"),
                "currency_symbol": invoice_to_process.get("currency_symbol"),
                "subscriptionPlan": subscription_plan_details
            }
            invoice_details.append(invoice_data)
            if invoice_to_process.get("status") == "paid":
                invoice_total = invoice_to_process.get("total", 0)
                if isinstance(invoice_total, (int, float)):
                    total_cost += float(invoice_total)
                elif isinstance(invoice_total, str):
                    try:
                        total_cost += float(invoice_total)
                    except (ValueError, TypeError):
                        pass
    except Exception as invoice_error:
        logger.warning("Could not fetch invoices from Zoho for company %s: %s", company_id, invoice_error)
    return invoice_details, total_cost
