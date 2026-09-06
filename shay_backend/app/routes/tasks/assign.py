"""
POST /{task_id}/assign endpoint (mounted at /api/v1/tasks): assign_task.

Split out of the former assignment.py (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md) alongside status_update.py,
which now holds the sibling POST /{task_id}/status endpoint. This
endpoint's own step-by-step logic (load/authorize, validate assignee,
apply assignment, build notification links) lives in the private sibling
_assign_helpers.py, which is not reused by any other endpoint.
"""

from fastapi import APIRouter, Depends, Request, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.services.audit_service import log as audit_log_write
from app.schemas.task import TaskResponse, TaskAssignmentRequest

from ._shared import build_task_response
from ._details import load_task_details
from .notifications_dispatch import process_task_reassignment_notifications
from ._assign_helpers import (
    load_task_and_check_access,
    validate_assignee,
    apply_assignment,
    build_reassignment_links,
)

router = APIRouter()


@router.post("/{task_id}/assign", response_model=TaskResponse)
async def assign_task(
    task_id: str,
    assignment_data: TaskAssignmentRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> TaskResponse:
    """Assign a task to a user"""
    user = await get_current_user_required(request, db)

    task, channel_id, thread_id = await load_task_and_check_access(task_id, user, db)
    await validate_assignee(assignment_data, user, channel_id, db)

    is_reassignment = apply_assignment(task, assignment_data, user)

    await audit_log_write(
        db, user.id, "task.assigned", "task", task.id,
        channel_id=task.channel_id, thread_id=task.thread_id,
        details={"assignee_id": str(assignment_data.assigned_to)}
    )
    await db.commit()

    # Process task reassignment notifications in background if reassigned
    if is_reassignment and task.assigned_to and channel_id and thread_id:
        redirect_url, notification_settings_url = await build_reassignment_links(channel_id, thread_id, db)

        background_tasks.add_task(
            process_task_reassignment_notifications,
            str(user.id),  # Reassigner ID
            str(task.assigned_to),  # Reassigned user ID
            str(channel_id),  # Channel ID
            redirect_url,  # Pre-constructed redirect URL
            notification_settings_url  # Pre-constructed notification settings URL
        )

    # Load checklists separately to avoid collection eager loading issues
    await db.refresh(task, attribute_names=['checklists'])

    # Load additional details manually
    details = await load_task_details(task, db)

    # Build response with details
    response = build_task_response(task, include_details=False)
    response.update(details)
    return response
