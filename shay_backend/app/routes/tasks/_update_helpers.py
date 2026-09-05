"""
Private helpers for update.py (PUT /{task_id}): access-check context
resolution, assignee validation, and field-update/reassignment-tracking
logic. Extracted so update.py's own handler body stays under the
150-line-per-file target; not reused by any other endpoint.
"""

from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.models.user import User
from app.models.channel_member import ChannelMember
from app.models.message import Message


async def resolve_task_channel_context(db: AsyncSession, task) -> tuple:
    """Resolve channel/thread/workspace ids from the task's message, for
    access checks and any optional message creation on update."""
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
    return task_channel_id, task_thread_id, task_workspace_id


async def check_update_access(db: AsyncSession, user, task, task_channel_id) -> None:
    """Raise 403 unless the user is a member of the task's channel or is
    the task's creator."""
    if not task_channel_id:
        return

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
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to task")


async def validate_reassignment_target(db: AsyncSession, user, task_data, task_channel_id) -> None:
    """If assigned_to is being changed, validate the new assignee exists,
    shares the user's company, and (when a channel is resolved) is a
    member of it."""
    if not task_data.assigned_to:
        return

    user_stmt = select(User).where(User.id == task_data.assigned_to)
    user_result = await db.execute(user_stmt)
    assigned_user = user_result.scalar_one_or_none()

    if not assigned_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assigned user not found")

    if assigned_user.company_id != user.company_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot assign task to user from different company"
        )

    if task_channel_id:
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


def apply_task_updates(task, task_data, user) -> None:
    """Apply update_data fields onto task, tracking status-close timestamps
    and reassignment history exactly as the original handler did."""
    update_data = task_data.dict(exclude_unset=True)

    is_reassignment = False
    previous_assignee = None
    if 'assigned_to' in update_data and task.assigned_to != update_data['assigned_to']:
        is_reassignment = True
        previous_assignee = task.assigned_to

    if 'status' in update_data:
        if update_data['status'] == 'Close' and task.status != 'Close':
            task.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        elif update_data['status'] != 'Close':
            task.completed_at = None

    for field, value in update_data.items():
        if hasattr(task, field):
            setattr(task, field, value)

    if is_reassignment:
        if not task.task_metadata:
            task.task_metadata = {}

        if 'assignee_changes' not in task.task_metadata:
            task.task_metadata['assignee_changes'] = []

        current_time = datetime.now(timezone.utc).replace(tzinfo=None)

        task.task_metadata['assignee_changes'].append({
            'previous_assignee': str(previous_assignee) if previous_assignee else None,
            'new_assignee': str(update_data['assigned_to']),
            'changed_by': str(user.id),
            'changed_at': current_time.isoformat(),
            'action': 'reassigned'
        })

    task.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    return is_reassignment
