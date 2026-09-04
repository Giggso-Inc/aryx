"""Timezone-normalization helpers shared by the eligibility/counting queries."""

from datetime import datetime, timezone


def ensure_timezone_aware(dt: datetime) -> datetime:
    """
    Ensure a datetime is timezone-aware (UTC).
    If the datetime is naive, assume it's UTC and add timezone info.

    Args:
        dt: Datetime object (may be naive or aware)

    Returns:
        Timezone-aware datetime in UTC
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        # If naive, assume it's UTC and make it aware
        return dt.replace(tzinfo=timezone.utc)
    # If already aware, convert to UTC
    return dt.astimezone(timezone.utc)


def datetime_for_db(dt: datetime) -> datetime:
    """
    Convert a datetime to naive UTC for database queries.
    Database DateTime columns are naive, so we need to convert timezone-aware
    datetimes to naive UTC before using them in queries.

    Args:
        dt: Datetime object (may be naive or aware)

    Returns:
        Naive datetime in UTC (for database queries)
    """
    if dt is None:
        return None
    # First ensure it's timezone-aware
    aware_dt = ensure_timezone_aware(dt)
    # Then convert to naive UTC (remove timezone info)
    return aware_dt.replace(tzinfo=None)
