"""
GET /{task_id} endpoint (mounted at /api/v1/tasks): get_task.

Split out of the former crud.py (part of the Phase 5a item 2 follow-up that
lowered the per-file target to 150 lines). Must be registered after
count.py/stats.py's literal `/count` and `/stats/overview` routes (see
app/routes/tasks/__init__.py) so this dynamic path doesn't swallow them.
"""

from fastapi import APIRouter, HTTPException, status, Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.task import Task
from app.models.channel_member import ChannelMember
from app.models.message import Message
from app.schemas.task import TaskResponse

from ._shared import build_task_response
from ._details import load_task_details, extract_task_history

router = APIRouter()


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> TaskResponse:
    """Get a specific task by ID"""
    user = await get_current_user_required(request, db)

    # Get task without eager loading to avoid collection issues
    stmt = select(Task).where(Task.id == task_id)
    result = await db.execute(stmt)
    task = result.scalar_one_or_none()

    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found"
        )

    # Check access through message -> channel membership
    if task.message_id:
        msg_stmt = select(Message).where(Message.id == task.message_id)
        msg_result = await db.execute(msg_stmt)
        msg = msg_result.scalar_one_or_none()
        if msg and msg.channel_id:
            channel_member_stmt = select(ChannelMember).where(
                and_(
                    ChannelMember.channel_id == msg.channel_id,
                    ChannelMember.user_id == user.id,
                    ChannelMember.is_active == True
                )
            )
            channel_member_result = await db.execute(channel_member_stmt)
            channel_member = channel_member_result.scalar_one_or_none()
            if not channel_member and str(task.created_by) != str(user.id):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied to task"
                )

    # Load checklists separately to avoid collection eager loading issues
    await db.refresh(task, attribute_names=['checklists'])

    # Load additional details manually
    details = await load_task_details(task, db)

    # Extract task history
    task_history = extract_task_history(task)

    # Build response with details
    response = build_task_response(task, include_details=False)
    response.update(details)

    # Add task history to response
    response['task_history'] = task_history

    return response
