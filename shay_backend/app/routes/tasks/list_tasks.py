"""
GET / endpoint (mounted at /api/v1/tasks): list_tasks.

Split out of the former listing.py (part of the Phase 5a item 2 follow-up
that lowered the per-file target to 150 lines). The endpoint's own logic
(paginated listing with per-task error recovery) is still large, so its
internal steps live in private sibling helpers (_list_tasks_helpers.py,
_list_tasks_response.py) that are not reused by any other endpoint.
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.schemas.task import TaskListResponse

from ._list_tasks_helpers import (
    get_user_channel_ids,
    get_visible_message_ids,
    build_filter_conditions,
)
from ._list_tasks_fetch import fetch_candidate_tasks
from ._list_tasks_response import build_enhanced_task_response

router = APIRouter()


@router.get("/", response_model=TaskListResponse)
async def list_tasks(
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1, description="Page number"),
    size: int = Query(10, ge=1, le=100, description="Page size"),
    status: Optional[str] = Query(None, description="Filter by status (comma-separated for multiple values, e.g., 'Open,In Progress,On Hold')"),
    priority: Optional[str] = Query(None, description="Filter by priority"),
    assigned_to: Optional[str] = Query(None, description="Filter by assigned user"),
    workspace_id: Optional[str] = Query(None, description="Filter by workspace (resolved via message)"),
    channel_id: Optional[str] = Query(None, description="Filter by channel (resolved via message)"),
    thread_id: Optional[str] = Query(None, description="Filter by thread (resolved via message)"),
    source: Optional[str] = Query(None, description="Filter by source"),
    tags: Optional[str] = Query(None, description="Filter by tags (comma-separated)"),
    created_by: Optional[str] = Query(None, description="Filter by task creator")
) -> TaskListResponse:
    """List tasks with enhanced details, history, and first task per thread limit"""
    user = await get_current_user_required(request, db)

    user_channel_ids = await get_user_channel_ids(db, user)
    if not user_channel_ids:
        return TaskListResponse(tasks=[], total=0, page=page, size=size, has_more=False)

    # Task model no longer has channel_id/thread_id/workspace_id columns.
    # Access control: get message IDs in user's channels, then find tasks by message_id.
    visible_message_ids = await get_visible_message_ids(
        db, user, user_channel_ids, thread_id, channel_id
    )
    if not visible_message_ids:
        return TaskListResponse(tasks=[], total=0, page=page, size=size, has_more=False)

    base_conditions = build_filter_conditions(
        visible_message_ids, status, priority, assigned_to, source, tags, created_by
    )

    tasks = await fetch_candidate_tasks(db, base_conditions, thread_id)

    # Apply post-fetch filters: exclude tasks with no message_id (orphans).
    # Note: status/priority/assigned_to/source/created_by/tags filters already applied above.
    filtered_tasks = [task for task in tasks if task.message_id is not None]

    # Apply pagination
    total = len(filtered_tasks)
    start_idx = (page - 1) * size
    end_idx = start_idx + size
    paginated_tasks = filtered_tasks[start_idx:end_idx]

    # Build enhanced responses
    enhanced_responses = []
    for task in paginated_tasks:
        entry = await build_enhanced_task_response(task, db)
        if entry is not None:
            enhanced_responses.append(entry)

    has_more = end_idx < total

    return TaskListResponse(
        tasks=enhanced_responses,
        total=total,
        page=page,
        size=size,
        has_more=has_more
    )
