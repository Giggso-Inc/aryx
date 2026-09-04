"""
Thread-scoped task endpoints (mounted at /api/v1/tasks):
  GET  /thread/{thread_id}            get_thread_task
  GET  /thread/{thread_id}/status     get_thread_task_status
  POST /thread/{thread_id}/create     create_thread_task
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, desc

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.services.audit_service import log as audit_log_write
from app.models.task import Task
from app.models.channel import Channel
from app.models.message import Message, Thread
from app.schemas.task import TaskCreate, TaskResponse

from ._shared import build_task_response, format_due_date_for_response
from ._details import load_task_details

router = APIRouter()


@router.get("/thread/{thread_id}", response_model=TaskResponse)
async def get_thread_task(
    thread_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> TaskResponse:
    """Get task associated with a specific thread"""
    user = await get_current_user_required(request, db)

    # Get thread
    thread_stmt = select(Thread).where(Thread.id == thread_id)
    thread_result = await db.execute(thread_stmt)
    thread = thread_result.scalar_one_or_none()

    if not thread:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Thread not found"
        )

    # Check access through channel
    channel_stmt = select(Channel).where(Channel.id == thread.channel_id)
    channel_result = await db.execute(channel_stmt)
    channel = channel_result.scalar_one_or_none()

    if not channel or not channel.is_accessible_by_user(user.company_id, user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to thread"
        )

    # Get task for this thread: find tasks whose message_id belongs to a message in this thread
    thread_msg_ids_stmt = select(Message.id).where(Message.thread_id == thread_id)
    thread_msg_ids_result = await db.execute(thread_msg_ids_stmt)
    thread_msg_ids = [row[0] for row in thread_msg_ids_result.all()]

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


@router.get("/thread/{thread_id}/status")
async def get_thread_task_status(
    thread_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> dict:
    """Check if a thread can accept new tasks (one active task per thread limit)"""
    user = await get_current_user_required(request, db)

    # Get thread
    thread_stmt = select(Thread).where(Thread.id == thread_id)
    thread_result = await db.execute(thread_stmt)
    thread = thread_result.scalar_one_or_none()

    if not thread:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Thread not found"
        )

    # Check access through channel
    channel_stmt = select(Channel).where(Channel.id == thread.channel_id)
    channel_result = await db.execute(channel_stmt)
    channel = channel_result.scalar_one_or_none()

    if not channel or not channel.is_accessible_by_user(user.company_id, user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to thread"
        )

    # Check for existing active tasks (via message IDs in this thread)
    thread_msg_ids_stmt = select(Message.id).where(Message.thread_id == thread_id)
    thread_msg_ids_result = await db.execute(thread_msg_ids_stmt)
    thread_msg_ids = [row[0] for row in thread_msg_ids_result.all()]

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


@router.post("/thread/{thread_id}/create", response_model=TaskResponse)
async def create_thread_task(
    thread_id: str,
    task_data: TaskCreate,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> TaskResponse:
    """Create a task for a specific thread (usually from first message)"""
    user = await get_current_user_required(request, db)

    # Get thread
    thread_stmt = select(Thread).where(Thread.id == thread_id)
    thread_result = await db.execute(thread_stmt)
    thread = thread_result.scalar_one_or_none()

    if not thread:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Thread not found"
        )

    # Check access through channel
    channel_stmt = select(Channel).where(Channel.id == thread.channel_id)
    channel_result = await db.execute(channel_stmt)
    channel = channel_result.scalar_one_or_none()

    if not channel or not channel.is_accessible_by_user(user.company_id, user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to thread"
        )

    # Get first message in thread for context
    first_message_stmt = select(Message).where(
        Message.thread_id == thread_id
    ).order_by(Message.sequence_number).limit(1)
    first_message_result = await db.execute(first_message_stmt)
    first_message = first_message_result.scalar_one_or_none()

    # Check if there's already an active task in this thread (via message IDs)
    thread_msg_ids_stmt = select(Message.id).where(Message.thread_id == thread_id)
    thread_msg_ids_result = await db.execute(thread_msg_ids_stmt)
    thread_msg_ids = [row[0] for row in thread_msg_ids_result.all()]

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
