"""
POST / endpoint (mounted at /api/v1/tasks): create_task.

Split out of the former crud.py (part of the Phase 5a item 2 follow-up that
lowered the per-file target to 150 lines). The endpoint's own logic (context
resolution, validation, optional message/attachment/checklist creation,
notification wiring) is still large, so its internal steps live in private
sibling helpers (_create_validation.py, _create_extras.py) that are not
reused by any other endpoint. The notification-dispatch block stays inline
here (rather than in a helper) because tests patch
`app.routes.tasks.create.link_shortener_service` /
`.process_task_assignment_notifications` directly on this module.
"""

import uuid

from fastapi import APIRouter, Request, Depends, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.config import settings
from app.middleware.auth_middleware import get_current_user_required
from app.services.audit_service import log as audit_log_write
from app.services.link_shortener_service import link_shortener_service
from app.models.task import Task
from app.schemas.task import TaskCreate, TaskResponse

from ._create_validation import (
    resolve_message_context,
    validate_workspace_channel_access,
    validate_assigned_user,
    check_no_active_task_in_thread,
)
from ._create_extras import attach_optional_message, create_task_checklists, build_create_response
from .notifications_dispatch import process_task_assignment_notifications

router = APIRouter()


@router.post("/", response_model=TaskResponse)
async def create_task(
    task_data: TaskCreate,
    background_tasks: BackgroundTasks,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> TaskResponse:
    """Create a new task with automatic context resolution from message_id"""
    user = await get_current_user_required(request, db)

    message, workspace, channel = await resolve_message_context(db, task_data.message_id)
    workspace_id = message.workspace_id
    channel_id = message.channel_id
    thread_id = message.thread_id

    await validate_workspace_channel_access(user, workspace, channel)
    await validate_assigned_user(db, user, task_data, channel_id)
    await check_no_active_task_in_thread(db, thread_id)

    # Create task linked via message_id only (no workspace_id/channel_id/thread_id columns)
    task = Task(
        id=uuid.uuid4(),
        title=task_data.title,
        description=task_data.description,
        assigned_to=task_data.assigned_to,
        created_by=user.id,
        status=task_data.status or "Open",
        source=task_data.source or "manual",
        due_date=task_data.due_date,
        message_id=task_data.message_id,
        priority=task_data.priority,
        tags=task_data.tags,
        task_metadata=task_data.task_metadata
    )

    db.add(task)
    await audit_log_write(db, user.id, "task.created", "task", task.id, channel_id=channel_id, thread_id=thread_id)
    await db.commit()

    await attach_optional_message(db, task, task_data, message, workspace_id, channel, channel_id, thread_id, user)
    await create_task_checklists(db, task, task_data)

    # Refresh the task object to ensure all fields are properly loaded
    await db.refresh(task)

    # Process task assignment notifications in background
    if task.assigned_to and channel_id and thread_id:
        # Use the canonical frontend root for real-time notifications.
        platform_url = settings.PLATFORM_URL

        try:
            redirect_url = await link_shortener_service.shorten(
                f"{platform_url}/threads/{channel_id}/{thread_id}?openTask=true", db,
                thread_id=thread_id, channel_id=channel_id, entity_type="task",
            ) if platform_url else "#"
            notification_settings_url = await link_shortener_service.shorten(
                f"{platform_url}/threads/{channel_id}?openSettings=true&tab=notification", db,
                channel_id=channel_id, entity_type="channel",
            ) if platform_url else "#"

        except Exception as e:
            print(f"Error constructing redirect URL: {e}")
            redirect_url = "#"
            notification_settings_url = "#"

        background_tasks.add_task(
            process_task_assignment_notifications,
            str(user.id),
            str(task.assigned_to),
            str(channel_id),
            task.title,
            redirect_url,
            notification_settings_url
        )

    return build_create_response(task)
