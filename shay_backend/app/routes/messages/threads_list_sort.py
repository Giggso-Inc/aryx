"""
list_threads sub-step: apply the sort_by/sort_order query params to the
thread listing query.

Split out of app/routes/messages/threads_list.py — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, wave B2.
"""

from typing import Optional

from sqlalchemy import func

from app.models.message import Thread


def apply_thread_sort(query, sort_by: Optional[str], sort_order: Optional[str]):
    """Return `query` with an ORDER BY applied per sort_by/sort_order.

    Supported sort_by values: created_at, updated_at, message_count,
    last_message_at (also the default for any unrecognized value).
    """
    ascending = (sort_order or "").lower() == "asc"

    if sort_by == "created_at":
        column = Thread.created_at
    elif sort_by == "updated_at":
        column = Thread.updated_at
    elif sort_by == "message_count":
        column = Thread.message_count
    else:  # Default: last_message_at
        column = func.coalesce(Thread.last_message_at, Thread.created_at)

    return query.order_by(column.asc() if ascending else column.desc())
