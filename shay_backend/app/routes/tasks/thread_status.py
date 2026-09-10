"""
GET /thread/{thread_id}/status endpoint (mounted at /api/v1/tasks):
get_thread_task_status.

Split out of the former thread_tasks.py (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md) alongside thread_detail.py
and thread_create.py, which now hold the sibling GET .../{thread_id} and
POST .../create endpoints. Shared thread/channel-access lookup lives in
_thread_tasks_shared.py.
"""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.task import Task

from ._shared import format_due_date_for_response
from ._thread_tasks_shared import load_thread_and_check_access, get_thread_message_ids

router = APIRouter()


@router.get("/thread/{thread_id}/status")
async def get_thread_task_status(
    thread_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> dict:
    """Check if a thread can accept new tasks (one active task per thread limit)"""
    user = await get_current_user_required(request, db)

    await load_thread_and_check_access(thread_id, user, db)

    # Check for existing active tasks (via message IDs in this thread)
    thread_msg_ids = await get_thread_message_ids(thread_id, db)

    existing_task = None
    if thread_msg_ids:
        existing_task_stmt = select(Task).where(
            and_(
                Task.message_id.in_(thread_msg_ids),
                Task.status.in_(["Open", "In Progress", "On Hold"])
            )
        )
        existing_task_result = await db.execute(existing_task_stmt)
        existing_task = existing_task_result.scalar_one_or_none()

    if existing_task:
        return {
            "thread_id": thread_id,
            "can_create_task": False,
            "existing_task": {
                "id": str(existing_task.id),
                "title": existing_task.title,
                "status": existing_task.status,
                "assigned_to": str(existing_task.assigned_to) if existing_task.assigned_to else None,
                "created_at": existing_task.created_at,
                "due_date": format_due_date_for_response(existing_task.due_date)
            },
            "message": f"Thread already has an active task: {existing_task.title}"
        }
    else:
        return {
            "thread_id": thread_id,
            "can_create_task": True,
            "existing_task": None,
            "message": "Thread can accept new tasks"
        }
