"""
Core task CRUD endpoints (mounted at /api/v1/tasks):
  POST   /            create_task
  GET    /{task_id}   get_task
  PUT    /{task_id}   update_task
  DELETE /{task_id}   delete_task

Stated exception (each of create_task/update_task is 200+ lines on its own,
well over the 150-line-per-file target for the whole module): every branch
in each of these two handlers (context resolution, validation, notification
wiring, optional message/attachment creation) is part of one atomic
request/response flow for a single endpoint. Splitting a handler's own body
across files would fragment one transaction's logic without isolating any
independently reusable concern, and would not change its actual line count.
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status, Request, Depends, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.core.database import get_db
from app.core.config import settings
from app.middleware.auth_middleware import get_current_user_required
from app.services.audit_service import log as audit_log_write
from app.services.link_shortener_service import link_shortener_service
from app.models.user import User
from app.models.task import Task
from app.models.workspace import Workspace
from app.models.channel import Channel
from app.models.channel_member import ChannelMember
from app.models.message import Message
from app.schemas.task import TaskCreate, TaskUpdate, TaskResponse

from ._shared import build_task_response, format_due_date_for_response
from ._details import load_task_details, extract_task_history
from .notifications_dispatch import process_task_assignment_notifications, process_task_reassignment_notifications

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

    # Get the message and validate access (message_id is now mandatory)
    message_stmt = select(Message).where(Message.id == task_data.message_id)
    message_result = await db.execute(message_stmt)
    message = message_result.scalar_one_or_none()

    if not message:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message not found"
        )

    # Get context from message
    workspace_id = message.workspace_id
    channel_id = message.channel_id
    thread_id = message.thread_id
    message_id = task_data.message_id

    # Validate workspace access
    workspace_stmt = select(Workspace).where(Workspace.id == workspace_id)
    workspace_result = await db.execute(workspace_stmt)
    workspace = workspace_result.scalar_one_or_none()

    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found"
        )

    # Check if user has access to workspace
    if workspace.company_id != user.company_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to workspace"
        )

    # Validate channel access
    channel_stmt = select(Channel).where(Channel.id == channel_id)
    channel_result = await db.execute(channel_stmt)
    channel = channel_result.scalar_one_or_none()

    if not channel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Channel not found"
        )

    # Check if user has access to channel
    if not channel.is_accessible_by_user(user.company_id, user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to channel"
        )

    # Validate assigned user
    assigned_user_stmt = select(User).where(User.id == task_data.assigned_to)
    assigned_user_result = await db.execute(assigned_user_stmt)
    assigned_user = assigned_user_result.scalar_one_or_none()

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

    # Validate that assigned user is a member of the channel
    from app.models.channel_member import ChannelMember
    channel_member_stmt = select(ChannelMember).where(
        and_(
            ChannelMember.channel_id == channel_id,
            ChannelMember.user_id == task_data.assigned_to,
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

    # Check if there's already an active task in this thread (via messages sharing the same thread)
    # Fetch all message IDs in the same thread and check for active tasks linked to them
    thread_messages_stmt = select(Message.id).where(Message.thread_id == thread_id)
    thread_messages_result = await db.execute(thread_messages_stmt)
    thread_message_ids = [row[0] for row in thread_messages_result.all()]

    if thread_message_ids:
        existing_task_stmt = select(Task).where(
            and_(
                Task.message_id.in_(thread_message_ids),
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

    assigned_to = task_data.assigned_to

    # Create task linked via message_id only (no workspace_id/channel_id/thread_id columns)
    task = Task(
        id=uuid.uuid4(),  # Pass UUID object directly, not string
        title=task_data.title,
        description=task_data.description,
        assigned_to=assigned_to,
        created_by=user.id,  # Set the user who created the task
        status=task_data.status or "Open",
        source=task_data.source or "manual",
        due_date=task_data.due_date,
        message_id=message_id,
        priority=task_data.priority,
        tags=task_data.tags,
        task_metadata=task_data.task_metadata
    )

    db.add(task)
    await audit_log_write(db, user.id, "task.created", "task", task.id, channel_id=channel_id, thread_id=thread_id)
    await db.commit()
    # Don't refresh the task to avoid potential async issues

    # Handle optional message content and attachments
    if task_data.message_content or task_data.attachment_ids:
        from app.core.auth import generate_message_id
        from app.models.attachment import Attachment

        # Create a new message with the provided content
        new_message = Message(
            id=generate_message_id(),
            content=task_data.message_content or f"Task created: {task_data.title}",
            message_type="user",
            thread_id=thread_id,
            channel_id=channel_id,
            workspace_id=workspace_id,
            user_id=user.id,
            sequence_number=message.sequence_number + 1  # Add after the original message
        )

        db.add(new_message)

        # Update channel metadata
        channel.message_count += 1
        channel.last_message_at = datetime.utcnow()

        await db.commit()
        await db.refresh(new_message)

        # Link attachments to the new message if provided
        if task_data.attachment_ids:
            for attachment_id in task_data.attachment_ids:
                try:
                    attachment_uuid = uuid.UUID(attachment_id)
                    attachment_stmt = select(Attachment).where(
                        and_(
                            Attachment.id == attachment_uuid,
                            Attachment.channel_id == channel_id,
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

        # Update task to reference the new message
        task.message_id = new_message.id
        await db.commit()

    # Create checklists if provided
    if task_data.checklists:
        from app.models.checklist import Checklist

        for i, checklist_item in enumerate(task_data.checklists):
            checklist = Checklist(
                id=uuid.uuid4(),  # Pass UUID object directly, not string
                task_id=task.id,  # task.id should already be UUID object
                text=checklist_item.get('text', f'Checklist Item {i+1}'),
                order_index=checklist_item.get('order_index', i),
                checklist_metadata=checklist_item.get('checklist_metadata')
            )
            db.add(checklist)

        await db.commit()

    # Refresh the task object to ensure all fields are properly loaded
    await db.refresh(task)

    # Process task assignment notifications in background
    if task.assigned_to and channel_id and thread_id:
        # Use the canonical frontend root for real-time notifications.
        platform_url = settings.PLATFORM_URL

        try:
            # Construct redirect URL (shortened; store thread_id/channel_id for move-safe links)
            redirect_url = await link_shortener_service.shorten(
                f"{platform_url}/threads/{channel_id}/{thread_id}?openTask=true", db,
                thread_id=thread_id, channel_id=channel_id, entity_type="task",
            ) if platform_url else "#"
            # Construct notification settings URL (shortened; channel-level)
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
            str(user.id),  # Task creator ID
            str(task.assigned_to),  # Assigned user ID
            str(channel_id),  # Channel ID
            task.title,  # Task title
            redirect_url,  # Pre-constructed redirect URL
            notification_settings_url  # Pre-constructed notification settings URL
        )

    # Build simple response to avoid async issues
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
        'completed_at': getattr(task, 'completed_at', None),
        'checklists': []
    }

    return response


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
    task_channel_id = None
    task_thread_id = None
    task_workspace_id = None
    if task.message_id:
        msg_stmt = select(Message).where(Message.id == task.message_id)
        msg_result = await db.execute(msg_stmt)
        msg = msg_result.scalar_one_or_none()
        if msg:
            task_channel_id = msg.channel_id
            task_thread_id = msg.thread_id
            task_workspace_id = msg.workspace_id

    # Check access through channel membership
    if task_channel_id:
        channel_member_stmt = select(ChannelMember).where(
            and_(
                ChannelMember.channel_id == task_channel_id,
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

    # Validate assigned user if provided
    if task_data.assigned_to:
        user_stmt = select(User).where(User.id == task_data.assigned_to)
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
        if task_channel_id:
            from app.models.channel_member import ChannelMember
            channel_member_stmt = select(ChannelMember).where(
                and_(
                    ChannelMember.channel_id == task_channel_id,
                    ChannelMember.user_id == task_data.assigned_to,
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

    # Update task fields
    update_data = task_data.dict(exclude_unset=True)

    # Check for reassignment before updating
    is_reassignment = False
    previous_assignee = None
    if 'assigned_to' in update_data and task.assigned_to != update_data['assigned_to']:
        is_reassignment = True
        previous_assignee = task.assigned_to

    # Handle status change
    if 'status' in update_data:
        if update_data['status'] == 'Close' and task.status != 'Close':
            # Use UTC time but convert to naive datetime for database compatibility
            task.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        elif update_data['status'] != 'Close':
            task.completed_at = None

    # Update other fields
    for field, value in update_data.items():
        if hasattr(task, field):
            setattr(task, field, value)

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
            'new_assignee': str(update_data['assigned_to']),
            'changed_by': str(user.id),
            'changed_at': current_time.isoformat(),
            'action': 'reassigned'
        })

    # Use UTC time but convert to naive datetime for database compatibility
    task.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await audit_log_write(db, user.id, "task.updated", "task", task.id, channel_id=task.channel_id, thread_id=task.thread_id)
    await db.commit()

    # Process task reassignment notifications in background if reassigned
    if is_reassignment and task.assigned_to and task_channel_id and task_thread_id:
        # Use the canonical frontend root for real-time notifications.
        platform_url = settings.PLATFORM_URL

        # Construct redirect URL (shortened; store thread_id/channel_id for move-safe links)
        redirect_url = await link_shortener_service.shorten(
            f"{platform_url}/threads/{task_channel_id}/{task_thread_id}?openTask=true", db,
            thread_id=task_thread_id, channel_id=task_channel_id, entity_type="task",
        ) if platform_url else "#"
        # Construct notification settings URL (shortened; channel-level)
        notification_settings_url = await link_shortener_service.shorten(
            f"{platform_url}/threads/{task_channel_id}?openSettings=true&tab=notification", db,
            channel_id=task_channel_id, entity_type="channel",
        ) if platform_url else "#"

        background_tasks.add_task(
            process_task_reassignment_notifications,
            str(user.id),  # Reassigner ID
            str(task.assigned_to),  # Reassigned user ID
            str(task_channel_id),  # Channel ID
            redirect_url,  # Pre-constructed redirect URL
            notification_settings_url  # Pre-constructed notification settings URL
        )

    # Handle optional message content and attachments for task update
    if task_data.message_content or task_data.attachment_ids:
        from app.core.auth import generate_message_id
        from app.models.attachment import Attachment

        # Get the thread to create a message
        if task_thread_id:
            # Create a new message with the provided content
            new_message = Message(
                id=generate_message_id(),
                content=task_data.message_content or f"Task updated: {task.title}",
                message_type="user",
                thread_id=task_thread_id,
                channel_id=task_channel_id,
                workspace_id=task_workspace_id,
                user_id=user.id,
                sequence_number=1  # Will be updated by the message system
            )

            db.add(new_message)

            # Update channel metadata
            if task_channel_id:
                channel_stmt = select(Channel).where(Channel.id == task_channel_id)
                channel_result = await db.execute(channel_stmt)
                channel = channel_result.scalar_one_or_none()
                if channel:
                    channel.message_count += 1
                    channel.last_message_at = datetime.utcnow()

            await db.commit()
            await db.refresh(new_message)

            # Link attachments to the new message if provided
            if task_data.attachment_ids:
                for attachment_id in task_data.attachment_ids:
                    try:
                        attachment_uuid = uuid.UUID(attachment_id)
                        attachment_stmt = select(Attachment).where(
                            and_(
                                Attachment.id == attachment_uuid,
                                Attachment.channel_id == task_channel_id,
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

    # Load checklists separately to avoid collection eager loading issues
    await db.refresh(task, attribute_names=['checklists'])

    # Load additional details manually
    details = await load_task_details(task, db)

    # Build response with details
    response = build_task_response(task, include_details=False)
    response.update(details)
    return response


@router.delete("/{task_id}")
async def delete_task(
    task_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> dict:
    """Delete a task"""
    user = await get_current_user_required(request, db)

    # Get task
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

    # Delete task

    await audit_log_write(db, user.id, "task.deleted", "task", task.id, channel_id=task.channel_id, thread_id=task.thread_id)
    await db.delete(task)
    await db.commit()

    return {"message": "Task deleted successfully"}
