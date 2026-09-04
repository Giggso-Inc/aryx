"""
Shared pure/DB-helper functions used across the payment_gateway package.

Note (dead-code finding, documented not fixed — see the "Stated exception /
findings" note in tests/test_payment_gateway_characterization.py):
`parse_features_to_limits` and `extract_price_from_brackets` are defined
here but are not called anywhere in the original payment_gateway.py, nor
imported by any other module in the repo (confirmed by grep before the
split). They are carried over verbatim rather than removed, since removing
unused-but-public module-level functions is a behavior change outside the
scope of this file-split task.
"""

import json
import re
import uuid
from typing import Any, Dict, Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.subscription import Subscription
from app.models.subscription_plan import SubscriptionPlan
from app.models.attachment import Attachment
from app.models.email_attachment import EmailAttachment
from app.models.datasource import Datasource
from app.services.zoho_service import get_zoho_service

import logging

logger = logging.getLogger(__name__)


def _is_missing_table_error(exc: Exception) -> bool:
    """True if any table used by the API is missing. Used only in the exception handler; success path is unchanged."""
    msg = str(exc).lower()
    return "does not exist" in msg or "undefinedtableerror" in msg


def _is_valid_uuid(value: str) -> bool:
    """Return True if value is a valid UUID string (32–36 chars, valid hex/hyphens)."""
    if not value or not isinstance(value, str):
        return False
    try:
        uuid.UUID(value)
        return True
    except (ValueError, TypeError):
        return False


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


def parse_features_to_limits(features: Any) -> Dict[str, int]:
    """
    Parse features from subscription plan to extract limits.

    Features can be in format like: ["5 Channels", "10 Messages", "5GB Storage"]
    Returns a dictionary with channelLimit, messageLimit, and StorageLimit.
    """
    limits = {
        "channelLimit": 0,
        "messageLimit": 0,
        "StorageLimit": 0
    }

    if not features:
        return limits

    # Handle list format: ["5 Channels", "10 Messages", "5GB Storage"]
    features_list = []
    if isinstance(features, list):
        features_list = features
    elif isinstance(features, dict):
        # If it's a dict, extract values
        features_list = list(features.values())
    elif isinstance(features, str):
        # If it's a string, try to parse as JSON
        try:
            parsed = json.loads(features)
            if isinstance(parsed, list):
                features_list = parsed
            elif isinstance(parsed, dict):
                features_list = list(parsed.values())
        except:
            features_list = [features]

    # Parse each feature string
    for feature in features_list:
        if not isinstance(feature, str):
            continue

        feature_lower = feature.lower()

        # Extract number and unit
        # Pattern: "5 Channels", "10 Messages", "5GB Storage", "5 GB Storage"
        # Try pattern with storage unit first (GB, MB, KB): "5GB Storage" or "5 GB Storage"
        match = re.search(r'(\d+(?:\.\d+)?)\s*([kmg]b)\s*(channel|message|storage)', feature_lower)
        if match:
            number = float(match.group(1))
            unit = match.group(2).lower()
            feature_type = match.group(3)
        else:
            # Try pattern without unit: "5 Channels", "10 Messages"
            match = re.search(r'(\d+(?:\.\d+)?)\s+(channel|message|storage)', feature_lower)
            if match:
                number = float(match.group(1))
                unit = ""
                feature_type = match.group(2)
            else:
                continue

        # Convert to base units
        if feature_type == "channel":
            limits["channelLimit"] = int(number)
        elif feature_type == "message":
            limits["messageLimit"] = int(number)
        elif feature_type == "storage":
            # Convert storage to bytes (GB -> bytes)
            if unit == "gb":
                limits["StorageLimit"] = int(number * 1024 * 1024 * 1024)  # GB to bytes
            elif unit == "mb":
                limits["StorageLimit"] = int(number * 1024 * 1024)  # MB to bytes
            elif unit == "kb":
                limits["StorageLimit"] = int(number * 1024)  # KB to bytes
            else:
                # Assume bytes if no unit
                limits["StorageLimit"] = int(number)

    return limits


def extract_price_from_brackets(addon: Dict[str, Any]) -> Optional[float]:
    """
    Extract price from price_brackets array.

    Zoho API returns price in price_brackets format, not as a direct price field.
    This helper extracts the price from the first price bracket.

    Args:
        addon: Addon data dictionary from Zoho API

    Returns:
        Price as float, or None if not found
    """
    price_brackets = addon.get('price_brackets', [])
    if price_brackets and len(price_brackets) > 0:
        # Get the first price bracket's price
        first_bracket = price_brackets[0]
        if isinstance(first_bracket, dict) and 'price' in first_bracket:
            try:
                return float(first_bracket.get('price', 0))
            except (ValueError, TypeError):
                pass
    # Fallback to direct price field if available
    price = addon.get('price')
    if price is not None:
        try:
            return float(price)
        except (ValueError, TypeError):
            pass
    return None


def _parse_channel_limit_from_features(features: Any) -> int:
    """
    Parse channel limit from subscription_plan features JSON.
    Features format example: ["4 Channels", "10GB Storage"] or ["Unlimited Channels"]
    Returns the numeric limit, -1 for unlimited, or 0 if not found.
    """
    if features is None:
        return 0
    if isinstance(features, list):
        for item in features:
            if isinstance(item, str):
                # Check for "Unlimited Channels" first
                if re.search(r"unlimited\s+channels?", item, re.IGNORECASE):
                    return -1  # -1 indicates unlimited
                # Check for numeric channel limit
                m = re.search(r"(\d+)\s*Channels?", item, re.IGNORECASE)
                if m:
                    return int(m.group(1))
    if isinstance(features, dict):
        for k, v in features.items():
            if "channel" in str(k).lower():
                if isinstance(v, str) and re.search(r"unlimited", v, re.IGNORECASE):
                    return -1  # -1 indicates unlimited
                elif isinstance(v, (int, float)):
                    return int(v)
    return 0


def _parse_message_limit_from_features(features: Any) -> int:
    """
    Parse message limit (per channel) from subscription_plan features JSON.
    Features format example: ["4 Channels", "50 messages", "10GB Storage"] or ["Unlimited Messages"]
    Returns the numeric limit per channel, -1 for unlimited, or 0 if not found.
    """
    if features is None:
        return 0
    if isinstance(features, list):
        for item in features:
            if isinstance(item, str):
                # Check for "Unlimited Messages" first
                if re.search(r"unlimited\s+messages?", item, re.IGNORECASE):
                    return -1  # -1 indicates unlimited
                # Check for numeric message limit (handles "2000 Messages per Channel" pattern)
                m = re.search(r"(\d+)\s*Messages?", item, re.IGNORECASE)
                if m:
                    return int(m.group(1))
    if isinstance(features, dict):
        for k, v in features.items():
            if "message" in str(k).lower():
                if isinstance(v, str) and re.search(r"unlimited", v, re.IGNORECASE):
                    return -1  # -1 indicates unlimited
                elif isinstance(v, (int, float)):
                    return int(v)
    return 0


def _parse_storage_limit_from_features(features: Any) -> int:
    """
    Parse storage limit (in bytes) from subscription_plan features JSON.
    Features format example: ["4 Channels", "10GB Storage"] or ["Unlimited Storage"]
    Supports: GB, MB, KB, B (case-insensitive)
    Returns the limit in bytes, -1 for unlimited, or 0 if not found.
    """
    if features is None:
        return 0

    if isinstance(features, list):
        for item in features:
            if isinstance(item, str):
                # Check for "Unlimited Storage" first
                if re.search(r"unlimited\s+storage", item, re.IGNORECASE):
                    return -1  # -1 indicates unlimited
                # Match patterns like "10GB Storage", "10 GB", "10GB", "200 MB Data Storage per Channel", etc.
                m = re.search(r"(\d+(?:\.\d+)?)\s*(GB|MB|KB|B).*?Storage", item, re.IGNORECASE)
                if m:
                    size_value = float(m.group(1))
                    unit = m.group(2).upper()

                    # Convert to bytes
                    if unit == "GB":
                        return int(size_value * 1024 * 1024 * 1024)
                    elif unit == "MB":
                        return int(size_value * 1024 * 1024)
                    elif unit == "KB":
                        return int(size_value * 1024)
                    elif unit == "B":
                        return int(size_value)

    if isinstance(features, dict):
        for k, v in features.items():
            if "storage" in str(k).lower():
                if isinstance(v, str) and re.search(r"unlimited", v, re.IGNORECASE):
                    return -1  # -1 indicates unlimited
                elif isinstance(v, (int, float)):
                    # Assume bytes if numeric
                    return int(v)
                elif isinstance(v, str):
                    # Parse string like "10GB"
                    m = re.search(r"(\d+(?:\.\d+)?)\s*(GB|MB|KB|B)", v, re.IGNORECASE)
                    if m:
                        size_value = float(m.group(1))
                        unit = m.group(2).upper()
                        if unit == "GB":
                            return int(size_value * 1024 * 1024 * 1024)
                        elif unit == "MB":
                            return int(size_value * 1024 * 1024)
                        elif unit == "KB":
                            return int(size_value * 1024)
                        elif unit == "B":
                            return int(size_value)
    return 0


async def _get_channel_storage_total(db: AsyncSession, channel_id: Any) -> int:
    """
    Return total storage in bytes for a channel: Attachment + EmailAttachment + Datasource file_size.
    Used for both marketplace (vs MARKETPLACE_STORAGE_LIMIT_MB) and SaaS (vs plan storage limit).
    """
    attachment_size_result = await db.execute(
        select(func.coalesce(func.sum(Attachment.file_size), 0)).where(
            Attachment.channel_id == channel_id
        )
    )
    attachment_size = attachment_size_result.scalar() or 0
    email_attachment_size_result = await db.execute(
        select(func.coalesce(func.sum(EmailAttachment.file_size), 0)).where(
            EmailAttachment.channel_id == channel_id
        )
    )
    email_attachment_size = email_attachment_size_result.scalar() or 0
    datasource_size_result = await db.execute(
        select(func.coalesce(func.sum(Datasource.file_size), 0)).where(
            Datasource.channel_id == channel_id
        )
    )
    datasource_size = datasource_size_result.scalar() or 0
    return int(attachment_size) + int(email_attachment_size) + int(datasource_size)
