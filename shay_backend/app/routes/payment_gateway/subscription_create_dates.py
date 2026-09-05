"""
Date/billing-cycle/status parsing helper for create_zoho_subscription
(subscription_create.py). Split out of that ~260-line handler so the
orchestrator can stay small; see subscription_create.py's module docstring
for the split rationale.
"""

import logging
import re
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


def parse_subscription_fields(zoho_subscription: dict) -> dict:
    """Parse dates, billing cycle, and local status from a Zoho subscription
    payload. Returns a dict with created_time, next_billing_date,
    current_period_start, current_period_end, billing_cycle, local_status."""
    created_time_str = zoho_subscription.get('created_time')
    next_billing_at_str = zoho_subscription.get('next_billing_at')

    created_time = datetime.utcnow()
    if created_time_str:
        try:
            # Parse ISO format: "2016-06-11T17:57:13-0700" or "2016-06-11"
            match = re.match(r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})', created_time_str)
            if match:
                created_time = datetime.strptime(match.group(1), "%Y-%m-%dT%H:%M:%S")
            else:
                created_time = datetime.strptime(created_time_str.split('T')[0], "%Y-%m-%d")
        except Exception as date_error:
            logger.warning(f"Could not parse created_time: {date_error}")
            created_time = datetime.utcnow()

    next_billing_date = None
    if next_billing_at_str:
        try:
            next_billing_date = datetime.strptime(next_billing_at_str, "%Y-%m-%d")
        except Exception as date_error:
            logger.warning(f"Could not parse next_billing_at: {date_error}")

    # Note: expires_at is stored as string in Java code, but we'll parse it if needed
    # For now, we'll store it in usage_limits or skip if not critical

    # Determine billing cycle and period end
    interval = zoho_subscription.get('interval', 1)
    interval_unit = zoho_subscription.get('interval_unit', 'months')
    billing_cycle = f"{interval} {interval_unit}"

    if interval_unit.lower() in ["year", "years"]:
        period_days = 365 * interval
    else:
        period_days = 30 * interval

    current_term_starts_at = zoho_subscription.get('current_term_starts_at')
    current_term_ends_at = zoho_subscription.get('current_term_ends_at')

    current_period_start = created_time
    if current_term_starts_at:
        try:
            current_period_start = datetime.strptime(current_term_starts_at, "%Y-%m-%d")
        except Exception:
            pass

    current_period_end = current_period_start + timedelta(days=period_days)
    if current_term_ends_at:
        try:
            current_period_end = datetime.strptime(current_term_ends_at, "%Y-%m-%d")
        except Exception:
            pass

    # Get subscription status from Zoho
    zoho_status = zoho_subscription.get('status', 'active')
    local_status = 'active' if zoho_status in ['live', 'active'] else zoho_status

    return {
        "created_time": created_time,
        "next_billing_date": next_billing_date,
        "billing_cycle": billing_cycle,
        "current_period_start": current_period_start,
        "current_period_end": current_period_end,
        "local_status": local_status,
    }
