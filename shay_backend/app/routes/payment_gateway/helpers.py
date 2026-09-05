"""
Shared pure/DB-helper functions used across the payment_gateway package.

Split from the original 378-line helpers.py grab-bag (Raven style
compliance, wave B). This file keeps only the two tiny, generic,
cross-cutting helpers used by exception handlers and ID validation across
the package. Sibling modules hold the other, more specific clusters:
  - helpers_invoice.py       -> Zoho invoice fetch/reconcile for a company
  - helpers_feature_limits.py -> dead-code feature-limit parsers (see note)
  - helpers_feature_parsing.py -> channel/message/storage limit parsers
  - helpers_storage.py       -> per-channel storage total aggregation
"""

import uuid


def _is_missing_table_error(exc: Exception) -> bool:
    """True if any table used by the API is missing. Used only in the exception handler; success path is unchanged."""
    msg = str(exc).lower()
    return "does not exist" in msg or "undefinedtableerror" in msg


def _is_valid_uuid(value: str) -> bool:
    """Return True if value is a valid UUID string (32-36 chars, valid hex/hyphens)."""
    if not value or not isinstance(value, str):
        return False
    try:
        uuid.UUID(value)
        return True
    except (ValueError, TypeError):
        return False
