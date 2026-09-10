"""
PUT /{task_id} endpoint (mounted at /api/v1/tasks): update_task.

Split out of the former crud.py (part of the Phase 5a item 2 follow-up that
lowered the per-file target to 150 lines). The endpoint's own logic (access
checks, reassignment validation/tracking, optional message/attachment
creation, notification wiring) is still large, so its internal steps live
in private sibling helpers (_update_helpers.py, _update_extras.py) that are
not reused by any other endpoint.
"""

from fastapi import APIRouter, HTTPException, status, Request, Depends, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.config import settings
from app.middleware.auth_middleware import get_current_user_required
from app.services.audit_service import log as audit_log_write
from app.services.link_shortener_service import link_shortener_service
from app.models.task import Task
from app.schemas.task import TaskUpdate, TaskResponse

from ._shared import build_task_response
from ._details import load_task_details
from ._update_helpers import (
    resolve_task_channel_context,
    check_update_access,
    validate_reassignment_target,
    apply_task_updates,
)
from ._update_extras import attach_optional_update_message
from .notifications_dispatch import process_task_reassignment_notifications

router = APIRouter()


@router.put("/{task_id}", response_model=TaskResponse)
async def update_task(
    task_id: str,
    task_data: TaskUpdate,
    background_tasks: BackgroundTasks,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> TaskResponse:
    """Update a task"""
    user = await get_current_user_required(request, db)

    stmt = select(Task).where(Task.id == task_id)
    result = await db.execute(stmt)
    task = result.scalar_one_or_none()

    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    task_channel_id, task_thread_id, task_workspace_id = await resolve_task_channel_context(db, task)
    await check_update_access(db, user, task, task_channel_id)
    await validate_reassignment_target(db, user, task_data, task_channel_id)

    is_reassignment = apply_task_updates(task, task_data, user)

    await audit_log_write(db, user.id, "task.updated", "task", task.id, channel_id=task.channel_id, thread_id=task.thread_id)
    await db.commit()

    # Process task reassignment notifications in background if reassigned
    if is_reassignment and task.assigned_to and task_channel_id and task_thread_id:
        # Use the canonical frontend root for real-time notifications.
        platform_url = settings.PLATFORM_URL

        redirect_url = await link_shortener_service.shorten(
            f"{platform_url}/threads/{task_channel_id}/{task_thread_id}?openTask=true", db,
            thread_id=task_thread_id, channel_id=task_channel_id, entity_type="task",
        ) if platform_url else "#"
        notification_settings_url = await link_shortener_service.shorten(
            f"{platform_url}/threads/{task_channel_id}?openSettings=true&tab=notification", db,
            channel_id=task_channel_id, entity_type="channel",
        ) if platform_url else "#"

        background_tasks.add_task(
            process_task_reassignment_notifications,
            str(user.id),
            str(task.assigned_to),
            str(task_channel_id),
            redirect_url,
            notification_settings_url
        )

    await attach_optional_update_message(
        db, task, task_data, user, task_channel_id, task_thread_id, task_workspace_id
    )

    # Load checklists separately to avoid collection eager loading issues
    await db.refresh(task, attribute_names=['checklists'])

    # Load additional details manually
    details = await load_task_details(task, db)

    # Build response with details
    response = build_task_response(task, include_details=False)
    response.update(details)
    return response
