"""
Task assignment/status endpoints (mounted at /api/v1/tasks):
  POST /{task_id}/assign   assign_task
  POST /{task_id}/status   update_task_status
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.core.database import get_db
from app.core.config import settings
from app.middleware.auth_middleware import get_current_user_required
from app.services.link_shortener_service import link_shortener_service
from app.services.audit_service import log as audit_log_write
from app.models.user import User
from app.models.task import Task
from app.models.channel import Channel
from app.models.channel_member import ChannelMember
from app.models.message import Message
from app.schemas.task import TaskResponse, TaskAssignmentRequest, TaskStatusUpdateRequest

from ._shared import build_task_response, format_due_date_for_response
from ._details import load_task_details
from .notifications_dispatch import process_task_reassignment_notifications

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

    # Get task without eager loading to avoid collection issues
    stmt = select(Task).where(Task.id == task_id)
    result = await db.execute(stmt)
    task = result.scalar_one_or_none()

    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found"
        )

    # Resolve channel_id from message for access checks
    assign_channel_id = None
    assign_thread_id = None
    if task.message_id:
        msg_stmt = select(Message).where(Message.id == task.message_id)
        msg_result = await db.execute(msg_stmt)
        msg = msg_result.scalar_one_or_none()
        if msg:
            assign_channel_id = msg.channel_id
            assign_thread_id = msg.thread_id

    # Check access through channel membership
    if assign_channel_id:
        channel_member_stmt = select(ChannelMember).where(
            and_(
                ChannelMember.channel_id == assign_channel_id,
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

    # Validate assigned user
    user_stmt = select(User).where(User.id == assignment_data.assigned_to)
    user_result = await db.execute(user_stmt)
    assigned_user = user_result.scalar_one_or_none()

    if not assigned_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Assigned user not found"
        )

    # Check if assigned user is in the same company
    if assigned_user.company_id != user.company_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot assign task to user from different company"
        )

    # Validate that assigned user is a member of the channel (resolved via message)
    if assign_channel_id:
        from app.models.channel_member import ChannelMember
        channel_member_stmt = select(ChannelMember).where(
            and_(
                ChannelMember.channel_id == assign_channel_id,
                ChannelMember.user_id == assignment_data.assigned_to,
                ChannelMember.is_active == True
            )
        )
        channel_member_result = await db.execute(channel_member_stmt)
        channel_member = channel_member_result.scalar_one_or_none()

        if not channel_member:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Assigned user must be a member of the channel to receive tasks"
            )

    # Check if this is a reassignment (different from current assignee)
    is_reassignment = task.assigned_to != assignment_data.assigned_to
    previous_assignee = task.assigned_to

    # Assign task
    task.assigned_to = assignment_data.assigned_to
    # Use UTC time but convert to naive datetime for database compatibility
    task.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)

    # Track reassignment in task metadata if this is a reassignment
    if is_reassignment:
        if not task.task_metadata:
            task.task_metadata = {}

        if 'assignee_changes' not in task.task_metadata:
            task.task_metadata['assignee_changes'] = []

        # Get current time for tracking
        current_time = datetime.now(timezone.utc).replace(tzinfo=None)

        # Add reassignment history
        task.task_metadata['assignee_changes'].append({
            'previous_assignee': str(previous_assignee) if previous_assignee else None,
            'new_assignee': str(assignment_data.assigned_to),
            'changed_by': str(user.id),
            'changed_at': current_time.isoformat(),
            'action': 'reassigned'
        })

    await audit_log_write(db, user.id, "task.assigned", "task", task.id, channel_id=task.channel_id, thread_id=task.thread_id, details={"assignee_id": str(assignment_data.assigned_to)})
    await db.commit()

    # Process task reassignment notifications in background if reassigned
    if is_reassignment and task.assigned_to and assign_channel_id and assign_thread_id:
        # Use the canonical frontend root for real-time notifications.
        platform_url = settings.PLATFORM_URL

        # Construct redirect URL (shortened; store thread_id/channel_id for move-safe links)
        redirect_url = await link_shortener_service.shorten(
            f"{platform_url}/threads/{assign_channel_id}/{assign_thread_id}?openTask=true", db,
            thread_id=assign_thread_id, channel_id=assign_channel_id, entity_type="task",
        ) if platform_url else "#"
        # Construct notification settings URL (shortened; channel-level)
        notification_settings_url = await link_shortener_service.shorten(
            f"{platform_url}/threads/{assign_channel_id}?openSettings=true&tab=notification", db,
            channel_id=assign_channel_id, entity_type="channel",
        ) if platform_url else "#"

        background_tasks.add_task(
            process_task_reassignment_notifications,
            str(user.id),  # Reassigner ID
            str(task.assigned_to),  # Reassigned user ID
            str(assign_channel_id),  # Channel ID
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
        from app.core.auth import generate_message_id
        from app.models.attachment import Attachment

        # Get the thread to create a message
        if status_thread_id:
            # Create a new message with the provided content
            new_message = Message(
                id=generate_message_id(),
                content=status_data.message_content or f"Task status updated to {status_data.status}",
                message_type="user",
                thread_id=status_thread_id,
                channel_id=status_channel_id,
                workspace_id=status_workspace_id,
                user_id=user.id,
                sequence_number=1  # Will be updated by the message system
            )

            db.add(new_message)

            # Update channel metadata
            if status_channel_id:
                channel_stmt = select(Channel).where(Channel.id == status_channel_id)
                channel_result = await db.execute(channel_stmt)
                channel = channel_result.scalar_one_or_none()
                if channel:
                    channel.message_count += 1
                    channel.last_message_at = datetime.utcnow()

            await db.commit()
            await db.refresh(new_message)

            # Link attachments to the new message if provided
            if status_data.attachment_ids:
                for attachment_id in status_data.attachment_ids:
                    try:
                        attachment_uuid = uuid.UUID(attachment_id)
                        attachment_stmt = select(Attachment).where(
                            and_(
                                Attachment.id == attachment_uuid,
                                Attachment.channel_id == status_channel_id,
                                Attachment.user_id == user.id  # Ensure user owns the attachment
                            )
                        )
                        attachment_result = await db.execute(attachment_stmt)
                        attachment = attachment_result.scalar_one_or_none()

                        if attachment:
                            # Link attachment to the new message
                            attachment.message_id = new_message.id
                        else:
                            raise HTTPException(
                                status_code=status.HTTP_404_NOT_FOUND,
                                detail=f"Attachment {attachment_id} not found or access denied"
                            )
                    except ValueError:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Invalid attachment ID format: {attachment_id}"
                        )

                await db.commit()

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
