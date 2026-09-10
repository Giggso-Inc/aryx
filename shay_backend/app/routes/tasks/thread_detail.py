"""
GET /thread/{thread_id} endpoint (mounted at /api/v1/tasks): get_thread_task.

Split out of the former thread_tasks.py (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md) alongside thread_status.py
and thread_create.py, which now hold the sibling GET .../status and POST
.../create endpoints. Shared thread/channel-access lookup lives in
_thread_tasks_shared.py.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.task import Task
from app.schemas.task import TaskResponse

from ._shared import build_task_response
from ._details import load_task_details
from ._thread_tasks_shared import load_thread_and_check_access, get_thread_message_ids

router = APIRouter()


@router.get("/thread/{thread_id}", response_model=TaskResponse)
async def get_thread_task(
    thread_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> TaskResponse:
    """Get task associated with a specific thread"""
    user = await get_current_user_required(request, db)

    await load_thread_and_check_access(thread_id, user, db)

    # Get task for this thread: find tasks whose message_id belongs to a message in this thread
    thread_msg_ids = await get_thread_message_ids(thread_id, db)

    task = None
    if thread_msg_ids:
        task_stmt = select(Task).where(Task.message_id.in_(thread_msg_ids)).order_by(desc(Task.created_at)).limit(1)
        task_result = await db.execute(task_stmt)
        task = task_result.scalar_one_or_none()

    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No task found for this thread"
        )

    # Load checklists separately to avoid collection eager loading issues
    await db.refresh(task, attribute_names=['checklists'])

    # Load additional details manually
    details = await load_task_details(task, db)

    # Build response with details
    response = build_task_response(task, include_details=False)
    response.update(details)
    return response
