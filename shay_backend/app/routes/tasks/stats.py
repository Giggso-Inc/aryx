"""
GET /stats/overview endpoint (mounted at /api/v1/tasks): get_task_stats.

Split out of the former listing.py (part of the Phase 5a item 2 follow-up
that lowered the per-file target to 150 lines). Must be registered before
detail.py's dynamic `GET /{task_id}` route (see app/routes/tasks/__init__.py).
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.task import Task
from app.models.channel import Channel
from app.models.message import Message
from app.schemas.task import TaskStats

router = APIRouter()


@router.get("/stats/overview", response_model=TaskStats)
async def get_task_stats(
    request: Request,
    db: AsyncSession = Depends(get_db),
    workspace_id: Optional[str] = Query(None, description="Filter by workspace"),
    channel_id: Optional[str] = Query(None, description="Filter by channel")
) -> TaskStats:
    """Get task statistics"""
    from app.models.workspace import Workspace

    user = await get_current_user_required(request, db)

    # Build base query for accessible channels (via company workspaces)
    workspace_query = select(Workspace.id).where(Workspace.company_id == user.company_id)
    if workspace_id:
        workspace_query = workspace_query.where(Workspace.id == workspace_id)

    workspace_result = await db.execute(workspace_query)
    accessible_workspaces = [str(w) for w in workspace_result.scalars().all()]

    if not accessible_workspaces:
        return TaskStats(
            total_tasks=0,
            open_tasks=0,
            in_progress_tasks=0,
            on_hold_tasks=0,
            closed_tasks=0,
            urgent_tasks=0
        )

    # Find channels in those workspaces
    channels_query = select(Channel.id).where(Channel.workspace_id.in_(accessible_workspaces))
    if channel_id:
        channels_query = channels_query.where(Channel.id == channel_id)
    channels_result = await db.execute(channels_query)
    accessible_channel_ids = [row[0] for row in channels_result.all()]

    if not accessible_channel_ids:
        return TaskStats(
            total_tasks=0,
            open_tasks=0,
            in_progress_tasks=0,
            on_hold_tasks=0,
            closed_tasks=0,
            urgent_tasks=0
        )

    # Find message IDs in those channels
    msg_ids_query = select(Message.id).where(Message.channel_id.in_(accessible_channel_ids))
    msg_ids_result = await db.execute(msg_ids_query)
    accessible_message_ids = [row[0] for row in msg_ids_result.all()]

    if not accessible_message_ids:
        return TaskStats(
            total_tasks=0,
            open_tasks=0,
            in_progress_tasks=0,
            on_hold_tasks=0,
            closed_tasks=0,
            urgent_tasks=0
        )

    # Build task query
    task_query = select(Task).where(Task.message_id.in_(accessible_message_ids))

    # Get all tasks for stats
    result = await db.execute(task_query)
    tasks = result.scalars().all()

    # Calculate stats
    total_tasks = len(tasks)
    open_tasks = len([t for t in tasks if t.status == 'Open'])
    in_progress_tasks = len([t for t in tasks if t.status == 'In Progress'])
    on_hold_tasks = len([t for t in tasks if t.status == 'On Hold'])
    closed_tasks = len([t for t in tasks if t.status == 'Close'])
    overdue_tasks = len([t for t in tasks if t.is_overdue])
    urgent_tasks = len([t for t in tasks if t.is_urgent])

    return TaskStats(
        total_tasks=total_tasks,
        open_tasks=open_tasks,
        in_progress_tasks=in_progress_tasks,
        on_hold_tasks=on_hold_tasks,
        closed_tasks=closed_tasks,
        overdue_tasks=overdue_tasks,
        urgent_tasks=urgent_tasks
    )
