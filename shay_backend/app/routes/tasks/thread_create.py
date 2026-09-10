"""
POST /thread/{thread_id}/create endpoint (mounted at /api/v1/tasks):
create_thread_task.

Split out of the former thread_tasks.py (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md) alongside thread_detail.py
and thread_status.py, which now hold the sibling GET .../{thread_id} and
GET .../status endpoints. Shared thread/channel-access lookup lives in
_thread_tasks_shared.py.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.services.audit_service import log as audit_log_write
from app.models.task import Task
from app.models.message import Message
from app.schemas.task import TaskCreate, TaskResponse

from ._shared import build_task_response
from ._details import load_task_details
from ._thread_tasks_shared import load_thread_and_check_access, get_thread_message_ids

router = APIRouter()


@router.post("/thread/{thread_id}/create", response_model=TaskResponse)
async def create_thread_task(
    thread_id: str,
    task_data: TaskCreate,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> TaskResponse:
    """Create a task for a specific thread (usually from first message)"""
    user = await get_current_user_required(request, db)

    thread, channel = await load_thread_and_check_access(thread_id, user, db)

    # Get first message in thread for context
    first_message_stmt = select(Message).where(
        Message.thread_id == thread_id
    ).order_by(Message.sequence_number).limit(1)
    first_message_result = await db.execute(first_message_stmt)
    first_message = first_message_result.scalar_one_or_none()

    # Check if there's already an active task in this thread (via message IDs)
    thread_msg_ids = await get_thread_message_ids(thread_id, db)

    if thread_msg_ids:
        existing_task_stmt = select(Task).where(
            and_(
                Task.message_id.in_(thread_msg_ids),
                Task.status.in_(["Open", "In Progress", "On Hold"])  # Active statuses
            )
        )
        existing_task_result = await db.execute(existing_task_stmt)
        existing_task = existing_task_result.scalar_one_or_none()

        if existing_task:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Cannot create task: Thread already has an active task '{existing_task.title}' (ID: {existing_task.id}) with status '{existing_task.status}'. Only one active task allowed per thread."
            )

    # Create task linked via message_id only (no workspace_id/channel_id/thread_id columns)
    task = Task(
        id=uuid.uuid4(),  # Pass UUID object directly, not string
        title=task_data.title or f"Task for Thread {thread.title or str(thread.id)[:8]}",
        description=task_data.description or (first_message.content[:200] + "..." if first_message and len(first_message.content) > 200 else first_message.content if first_message else None),
        assigned_to=task_data.assigned_to,
        created_by=user.id,
        status=task_data.status,
        source=task_data.source or "manual",
        due_date=task_data.due_date,
        message_id=first_message.id if first_message else None,
        priority=task_data.priority,
        tags=task_data.tags,
        task_metadata={
            **(task_data.task_metadata or {}),
            "thread_title": thread.title,
            "channel_name": channel.name,
            "created_from_message": str(first_message.id) if first_message else None
        }
    )

    db.add(task)
    await audit_log_write(db, user.id, "task.created", "task", task.id, channel_id=thread.channel_id, thread_id=thread.id)
    await db.commit()
    # Load checklists separately to avoid collection eager loading issues
    await db.refresh(task, attribute_names=['checklists'])

    # Load additional details manually
    details = await load_task_details(task, db)

    # Build response with details
    response = build_task_response(task, include_details=False)
    response.update(details)
    return response
