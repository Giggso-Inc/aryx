"""
Private helpers for assign.py's POST /{task_id}/assign endpoint.

Not reused by any other endpoint — split out purely to keep assign.py
itself under the 150-line style target. No routes are defined here.
"""

from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.core.config import settings
from app.services.link_shortener_service import link_shortener_service
from app.models.user import User
from app.models.task import Task
from app.models.channel_member import ChannelMember
from app.models.message import Message
from app.schemas.task import TaskAssignmentRequest


async def load_task_and_check_access(task_id: str, user: User, db: AsyncSession) -> tuple[Task, object, object]:
    """Load the task, resolve its channel/thread via its message, and enforce
    channel-membership access. Returns (task, channel_id, thread_id)."""
    stmt = select(Task).where(Task.id == task_id)
    result = await db.execute(stmt)
    task = result.scalar_one_or_none()

    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    channel_id = None
    thread_id = None
    if task.message_id:
        msg_stmt = select(Message).where(Message.id == task.message_id)
        msg_result = await db.execute(msg_stmt)
        msg = msg_result.scalar_one_or_none()
        if msg:
            channel_id = msg.channel_id
            thread_id = msg.thread_id

    if channel_id:
        channel_member_stmt = select(ChannelMember).where(
            and_(
                ChannelMember.channel_id == channel_id,
                ChannelMember.user_id == user.id,
                ChannelMember.is_active == True
            )
        )
        channel_member_result = await db.execute(channel_member_stmt)
        channel_member = channel_member_result.scalar_one_or_none()
        if not channel_member and str(task.created_by) != str(user.id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to task")

    return task, channel_id, thread_id


async def validate_assignee(assignment_data: TaskAssignmentRequest, user: User, channel_id: object, db: AsyncSession) -> User:
    """Validate the target assignee exists, shares the requester's company,
    and (when a channel is resolved) is a member of that channel."""
    user_stmt = select(User).where(User.id == assignment_data.assigned_to)
    user_result = await db.execute(user_stmt)
    assigned_user = user_result.scalar_one_or_none()

    if not assigned_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assigned user not found")

    if assigned_user.company_id != user.company_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot assign task to user from different company"
        )

    if channel_id:
        channel_member_stmt = select(ChannelMember).where(
            and_(
                ChannelMember.channel_id == channel_id,
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

    return assigned_user


def apply_assignment(task: Task, assignment_data: TaskAssignmentRequest, user: User) -> bool:
    """Mutate `task` in place with the new assignee, tracking reassignment
    history in task_metadata. Returns whether this was a reassignment."""
    is_reassignment = task.assigned_to != assignment_data.assigned_to
    previous_assignee = task.assigned_to

    task.assigned_to = assignment_data.assigned_to
    task.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)

    if is_reassignment:
        if not task.task_metadata:
            task.task_metadata = {}
        if 'assignee_changes' not in task.task_metadata:
            task.task_metadata['assignee_changes'] = []

        current_time = datetime.now(timezone.utc).replace(tzinfo=None)
        task.task_metadata['assignee_changes'].append({
            'previous_assignee': str(previous_assignee) if previous_assignee else None,
            'new_assignee': str(assignment_data.assigned_to),
            'changed_by': str(user.id),
            'changed_at': current_time.isoformat(),
            'action': 'reassigned'
        })

    return is_reassignment


async def build_reassignment_links(channel_id: object, thread_id: object, db: AsyncSession) -> tuple[str, str]:
    """Build the (redirect_url, notification_settings_url) pair used by the
    reassignment background notification task."""
    platform_url = settings.PLATFORM_URL

    redirect_url = await link_shortener_service.shorten(
        f"{platform_url}/threads/{channel_id}/{thread_id}?openTask=true", db,
        thread_id=thread_id, channel_id=channel_id, entity_type="task",
    ) if platform_url else "#"

    notification_settings_url = await link_shortener_service.shorten(
        f"{platform_url}/threads/{channel_id}?openSettings=true&tab=notification", db,
        channel_id=channel_id, entity_type="channel",
    ) if platform_url else "#"

    return redirect_url, notification_settings_url
