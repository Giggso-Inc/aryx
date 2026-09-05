"""
Zoho date-string parsing for validate_payment_persist.

Extracted from validate_payment.py's DB-persist block (Raven style
compliance, wave B): parses the `created_time` and `next_billing_at`
strings Zoho returns in the subscription payload.
"""

import logging
import re
from datetime import datetime
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


def _parse_subscription_dates(subscription_data: dict) -> Tuple[Optional[datetime], Optional[datetime]]:
    """Returns (created_time, next_billing_date), either of which may be None."""
    created_time_str = subscription_data.get('created_time')
    next_billing_at_str = subscription_data.get('next_billing_at')

    created_time = None
    next_billing_date = None

    if created_time_str:
        try:
            # Parse ISO format datetime: "2016-06-05T23:10:16-0700" or "2016-06-05T23:10:16-07:00"
            # Match pattern like "2016-06-05T23:10:16" or "2016-06-05T23:10:16-0700"
            match = re.match(r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})', created_time_str)
            if match:
                created_time = datetime.strptime(match.group(1), "%Y-%m-%dT%H:%M:%S")
            else:
                # Try simple date format
                created_time = datetime.strptime(created_time_str.split('T')[0], "%Y-%m-%d")
        except Exception as date_error:
            logger.warning(f"Could not parse created_time: {date_error}")
            created_time = datetime.utcnow()

    if next_billing_at_str:
        try:
            # Parse date format: "2016-06-30"
            next_billing_date = datetime.strptime(next_billing_at_str, "%Y-%m-%d")
        except Exception as date_error:
            logger.warning(f"Could not parse next_billing_at: {date_error}")

    return created_time, next_billing_date
