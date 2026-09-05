"""
Zoho invoice fetch/reconciliation for fetch_company_subscription_details.

Extracted from subscription_details.py: calls the Zoho API for customer
invoices, enriches each with full invoice details (name/code/subscription_id
from invoice_items), and computes total paid cost. All Zoho/network errors
are swallowed here exactly as in the original handler (logged as warnings,
empty invoice list returned) so a Zoho outage never fails the endpoint.
"""
import logging
from typing import Any, List, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.subscription import Subscription
from app.models.subscription_plan import SubscriptionPlan
from app.services.zoho_service import get_zoho_service

logger = logging.getLogger(__name__)


async def _fetch_invoice_details(
    db: AsyncSession,
    subscription: Subscription,
    plan: SubscriptionPlan,
    company_id: Any,
) -> Tuple[List[dict], float]:
    invoice_details: List[dict] = []
    total_cost = 0.0

    if not subscription.zoho_customer_id:
        return invoice_details, total_cost

    try:
        # Get ALL subscriptions for the company to match invoices to their
        # correct plans. NOTE: preserved verbatim from the original handler,
        # including its per-subscription plan lookup loop below, whose
        # result was never actually read by the original code either — kept
        # as-is to avoid changing the DB call sequence characterized by
        # tests/test_payment_gateway_characterization.py.
        all_subscriptions_result = await db.execute(
            select(Subscription)
            .where(Subscription.company_id == company_id)
            .order_by(Subscription.created_at.desc())
        )
        all_subscriptions = all_subscriptions_result.scalars().all()
        for sub in all_subscriptions:
            await db.execute(
                select(SubscriptionPlan).where(SubscriptionPlan.id == sub.plan_id)
            )

        # Determine platform_name from subscription or use default.
        # Default to 'prism7' to match the individual invoice endpoint behavior.
        zoho_service_instance = get_zoho_service('prism7')
        invoices = await zoho_service_instance.get_customer_invoices(subscription.zoho_customer_id)

        if invoices:
            for invoice in invoices:
                invoice_data, invoice_total_cost = await _reconcile_invoice(
                    zoho_service_instance, invoice, plan
                )
                invoice_details.append(invoice_data)
                total_cost += invoice_total_cost

        logger.info(f"Fetched {len(invoice_details)} invoices for customer {subscription.zoho_customer_id}")
    except Exception as invoice_error:
        logger.warning(f"Could not fetch invoices from Zoho: {invoice_error}")

    return invoice_details, total_cost


async def _reconcile_invoice(zoho_service_instance: Any, invoice: dict, plan: SubscriptionPlan) -> Tuple[dict, float]:
    """Fetch full Zoho invoice details for one invoice and build the response entry + paid cost."""
    invoice_id = invoice.get("invoice_id")

    full_invoice_data = None
    invoice_name = None
    invoice_code = None

    try:
        # Call the individual invoice retrieval API to get full details
        full_invoice_data = await zoho_service_instance.get_invoice(invoice_id)

        # subscription_id can be in invoice_items[0].subscription_id OR
        # subscriptions[0].subscription_id
        invoice_items = full_invoice_data.get("invoice_items", [])
        zoho_subscription_id = None
        if invoice_items:
            first_item = invoice_items[0]
            invoice_name = first_item.get("name")
            invoice_code = first_item.get("code")
            zoho_subscription_id = first_item.get("subscription_id")

        if not zoho_subscription_id and full_invoice_data.get("subscriptions"):
            subscriptions = full_invoice_data.get("subscriptions", [])
            if subscriptions:
                zoho_subscription_id = subscriptions[0].get("subscription_id")

        logger.info(
            f"✅ Extracted invoice details - invoice_id: {invoice_id}, "
            f"subscription_id: {zoho_subscription_id}, name: {invoice_name}, code: {invoice_code}"
        )
    except Exception as detail_error:
        logger.warning(f"⚠️ Could not fetch full invoice details for {invoice_id}: {detail_error}")

    invoice_to_process = full_invoice_data if full_invoice_data else invoice

    subscription_plan_details = {
        "name": invoice_name if invoice_name else plan.name,
        "planCode": invoice_code if invoice_code else plan.plan_code
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

    invoice_total_cost = 0.0
    if invoice_to_process.get("status") == "paid":
        invoice_total = invoice_to_process.get("total", 0)
        if isinstance(invoice_total, (int, float)):
            invoice_total_cost = float(invoice_total)
        elif isinstance(invoice_total, str):
            try:
                invoice_total_cost = float(invoice_total)
            except:
                pass

    return invoice_data, invoice_total_cost
