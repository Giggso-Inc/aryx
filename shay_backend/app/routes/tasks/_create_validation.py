"""
Private validation helpers for create.py (POST /). Extracted so create.py's
own handler body stays under the 150-line-per-file target; not reused by
any other endpoint.
"""

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.models.user import User
from app.models.task import Task
from app.models.workspace import Workspace
from app.models.channel import Channel
from app.models.channel_member import ChannelMember
from app.models.message import Message


async def resolve_message_context(db: AsyncSession, message_id) -> tuple:
    """Resolve and validate the message/workspace/channel a new task is
    created against. Returns (message, workspace, channel)."""
    message_stmt = select(Message).where(Message.id == message_id)
    message_result = await db.execute(message_stmt)
    message = message_result.scalar_one_or_none()

    if not message:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")

    workspace_stmt = select(Workspace).where(Workspace.id == message.workspace_id)
    workspace_result = await db.execute(workspace_stmt)
    workspace = workspace_result.scalar_one_or_none()

    if not workspace:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")

    channel_stmt = select(Channel).where(Channel.id == message.channel_id)
    channel_result = await db.execute(channel_stmt)
    channel = channel_result.scalar_one_or_none()

    if not channel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found")

    return message, workspace, channel


async def validate_workspace_channel_access(user, workspace, channel) -> None:
    """Check the requesting user has access to the resolved workspace/channel."""
    if workspace.company_id != user.company_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to workspace")

    if not channel.is_accessible_by_user(user.company_id, user.role):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to channel")


async def validate_assigned_user(db: AsyncSession, user, task_data, channel_id):
    """Validate the assignee: exists, same company, and a member of the channel."""
    assigned_user_stmt = select(User).where(User.id == task_data.assigned_to)
    assigned_user_result = await db.execute(assigned_user_stmt)
    assigned_user = assigned_user_result.scalar_one_or_none()

    if not assigned_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assigned user not found")

    if assigned_user.company_id != user.company_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot assign task to user from different company"
        )

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

    return assigned_user


async def check_no_active_task_in_thread(db: AsyncSession, thread_id) -> None:
    """Raise 409 if the thread (via its messages) already has an active task."""
    thread_messages_stmt = select(Message.id).where(Message.thread_id == thread_id)
    thread_messages_result = await db.execute(thread_messages_stmt)
    thread_message_ids = [row[0] for row in thread_messages_result.all()]

    if not thread_message_ids:
        return

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
            detail=(
                f"Cannot create task: Thread already has an active task "
                f"'{existing_task.title}' (ID: {existing_task.id}) with status "
                f"'{existing_task.status}'. Only one active task allowed per thread."
            )
        )
