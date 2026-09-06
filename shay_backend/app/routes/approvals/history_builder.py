"""
build_approval_history — orchestrates the timeline used by the list and
detail endpoints.

Originally a single ~200-line function reconstructing a chronological
timeline from three independent metadata shapes (initial_assignment,
reassignments, status_changes) plus a legacy fallback branch. Each shape is
its own metadata key with no shared mutable state between them, so they were
split into their own modules (history_timeline_initial.py,
history_timeline_changes.py) — this file just calls them and sorts the
combined result, preserving the exact original behavior and ordering.
build_approval_context moved to history_context.py (unrelated concern: it
resolves channel/workspace/thread context, not the timeline).
"""

from datetime import datetime
from typing import Any, Dict, List

from app.models.approval import Approval
from sqlalchemy.ext.asyncio import AsyncSession

from .history_timeline_changes import build_reassignment_entries, build_status_change_entries
from .history_timeline_initial import build_initial_assignment_entries


async def build_approval_history(approval: Approval, db: AsyncSession) -> List[Dict[str, Any]]:
    """
    Build approval history from metadata and approval data.
    This function now uses the same logic as the new history endpoint.

    Args:
        approval (Approval): The approval object
        db (AsyncSession): Database session

    Returns:
        List[Dict[str, Any]]: List of approval history items
    """
    metadata = approval.approval_metadata or {}

    history: List[Dict[str, Any]] = []
    history.extend(await build_initial_assignment_entries(approval, metadata, db))
    history.extend(await build_reassignment_entries(approval, metadata, db))
    history.extend(await build_status_change_entries(approval, metadata, db))

    # Sort history by timestamp (newest first)
    # Handle None timestamps by using a default datetime
    default_timestamp = datetime(1970, 1, 1)  # Unix epoch
    history.sort(key=lambda x: x['timestamp'] if x['timestamp'] is not None else default_timestamp, reverse=True)

    return history
