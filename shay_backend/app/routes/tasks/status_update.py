"""
POST /{task_id}/status endpoint (mounted at /api/v1/tasks): update_task_status.

Split out of the former assignment.py (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md) alongside assign.py, which
now holds the sibling POST /{task_id}/assign endpoint. The optional
message/attachment side effect of a status update lives in the private
sibling _status_update_message.py, which is not reused elsewhere.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.services.audit_service import log as audit_log_write
from app.models.task import Task
from app.models.channel_member import ChannelMember
from app.models.message import Message
from app.schemas.task import TaskResponse, TaskStatusUpdateRequest

from ._shared import format_due_date_for_response
from ._status_update_message import create_status_message_and_link_attachments

router = APIRouter()


@router.post("/{task_id}/status", response_model=TaskResponse)
async def update_task_status(
    task_id: str,
    status_data: TaskStatusUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> TaskResponse:
    """Update task status"""
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

    # Resolve channel/thread/workspace from message for access checks and message creation
    status_channel_id = None
    status_thread_id = None
    status_workspace_id = None
    if task.message_id:
        msg_stmt = select(Message).where(Message.id == task.message_id)
        msg_result = await db.execute(msg_stmt)
        msg = msg_result.scalar_one_or_none()
        if msg:
            status_channel_id = msg.channel_id
            status_thread_id = msg.thread_id
            status_workspace_id = msg.workspace_id

    # Check access through channel membership
    if status_channel_id:
        channel_member_stmt = select(ChannelMember).where(
            and_(
                ChannelMember.channel_id == status_channel_id,
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

    # Update status
    task.status = status_data.status

    # Handle completion
    if status_data.status == 'Close' and task.status != 'Close':
        # Use UTC time but convert to naive datetime for database compatibility
        task.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    elif status_data.status != 'Close':
        task.completed_at = None

    # Update metadata with status change comment if provided
    if status_data.comments:
        if not task.task_metadata:
            task.task_metadata = {}

        if 'status_changes' not in task.task_metadata:
            task.task_metadata['status_changes'] = []

        # Use UTC time but convert to naive datetime for database compatibility
        current_time = datetime.now(timezone.utc).replace(tzinfo=None)

        task.task_metadata['status_changes'].append({
            'status': status_data.status,
            'changed_by': str(user.id),
            'changed_at': current_time.isoformat(),
            'comments': status_data.comments
        })

    # Use UTC time but convert to naive datetime for database compatibility
    task.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await audit_log_write(db, user.id, "task.status_updated", "task", task.id, channel_id=task.channel_id, thread_id=task.thread_id, details={"status": status_data.status})
    await db.commit()

    # Handle optional message content and attachments for status update
    if status_data.message_content or status_data.attachment_ids:
        await create_status_message_and_link_attachments(
            task, status_data, status_channel_id, status_thread_id, status_workspace_id, user, db
        )

    # Refresh the task object to ensure all fields are properly loaded
    await db.refresh(task)

    # Build a simple response to avoid async issues
    response = {
        'id': str(task.id),
        'title': task.title,
        'description': task.description,
        'status': task.status,
        'source': task.source,
        'due_date': format_due_date_for_response(task.due_date),
        'priority': task.priority,
        'tags': task.tags,
        'task_metadata': task.task_metadata,
        'assigned_to': str(task.assigned_to) if task.assigned_to else None,
        'created_by': str(task.created_by) if task.created_by else None,
        'message_id': str(task.message_id) if task.message_id else None,
        'created_at': task.created_at,
        'updated_at': task.updated_at,
        'completed_at': task.completed_at.isoformat() if task.completed_at else None,
        'checklists': []
    }

    return response
