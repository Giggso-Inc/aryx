"""
Detail-loading helpers: resolve a task's assigned/creator user objects and
its channel/workspace/thread context via its message_id. Used by create,
detail, update, assign, and thread_tasks endpoints.

Split out of the original _details.py (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md): build_task_details and
build_task_context moved to the sibling _details_context.py, which is used
only by the task-list response path — that kept both files under the
150-line target without splitting apart functions that share callers.
"""

from typing import Any, Dict

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.user import User
from app.models.task import Task
from app.models.workspace import Workspace
from app.models.channel import Channel
from app.models.message import Message


async def load_task_details(task: Task, db: AsyncSession) -> Dict[str, Any]:
    """Load additional user and context details for a task"""
    details = {}

    # Load assigned user details
    if task.assigned_to:
        user_stmt = select(User).where(User.id == task.assigned_to)
        user_result = await db.execute(user_stmt)
        assigned_user = user_result.scalar_one_or_none()
        if assigned_user:
            details['assigned_user'] = {
                'id': assigned_user.id,
                'name': assigned_user.name,
                'email_id': assigned_user.email_id,
                'avatar_url': assigned_user.avatar_url,
                'role': assigned_user.role
            }

    # Load created by user details
    if hasattr(task, 'created_by') and task.created_by:
        user_stmt = select(User).where(User.id == task.created_by)
        user_result = await db.execute(user_stmt)
        created_by_user = user_result.scalar_one_or_none()
        if created_by_user:
            details['created_by'] = {
                'id': created_by_user.id,
                'name': created_by_user.name,
                'email_id': created_by_user.email_id,
                'avatar_url': created_by_user.avatar_url,
                'role': created_by_user.role
            }

    # Load channel/workspace details via message_id
    if hasattr(task, 'message_id') and task.message_id:
        msg_stmt = select(Message).where(Message.id == task.message_id)
        msg_result = await db.execute(msg_stmt)
        msg = msg_result.scalar_one_or_none()
        if msg and msg.channel_id:
            channel_stmt = select(Channel).where(Channel.id == msg.channel_id)
            channel_result = await db.execute(channel_stmt)
            channel = channel_result.scalar_one_or_none()
            if channel:
                details['channel'] = {
                    'id': channel.id,
                    'name': channel.name,
                    'description': channel.description,
                    'is_public': channel.is_public,
                    'is_active': channel.is_active,
                    'workspace_id': str(channel.workspace_id) if channel.workspace_id else None
                }
            if msg.workspace_id:
                workspace_stmt = select(Workspace).where(Workspace.id == msg.workspace_id)
                workspace_result = await db.execute(workspace_stmt)
                workspace = workspace_result.scalar_one_or_none()
                if workspace:
                    details['workspace'] = {
                        'id': workspace.id,
                        'name': workspace.name,
                        'description': workspace.description
                    }

    return details


def extract_task_history(task: Task) -> Dict[str, Any]:
    """Extract minimal task history from existing task data"""
    history = {
        'status_changes': [],
        'priority_changes': [],
        'assignee_changes': []
    }

    # Add current status as initial status
    history['status_changes'].append({
        'status': task.status,
        'changed_at': task.created_at.isoformat() if task.created_at else None,
        'changed_by': str(task.created_by) if task.created_by else None
    })

    # Add current priority as initial priority
    history['priority_changes'].append({
        'priority': task.priority,
        'changed_at': task.created_at.isoformat() if task.created_at else None,
        'changed_by': str(task.created_by) if task.created_by else None
    })

    # Add current assignee as initial assignment
    if task.assigned_to:
        history['assignee_changes'].append({
            'assigned_to': str(task.assigned_to),
            'changed_at': task.created_at.isoformat() if task.created_at else None,
            'changed_by': str(task.created_by) if task.created_by else None
        })

    # Extract status changes from metadata if available
    if task.task_metadata and isinstance(task.task_metadata, dict):
        if 'status_changes' in task.task_metadata:
            status_changes = task.task_metadata['status_changes']
            if isinstance(status_changes, list):
                for change in status_changes:
                    if isinstance(change, dict):
                        history['status_changes'].append({
                            'status': change.get('status'),
                            'changed_at': change.get('changed_at'),
                            'changed_by': change.get('changed_by'),
                            'comments': change.get('comments')
                        })

        # Extract priority changes from metadata if available
        if 'priority_changes' in task.task_metadata:
            priority_changes = task.task_metadata['priority_changes']
            if isinstance(priority_changes, list):
                for change in priority_changes:
                    if isinstance(change, dict):
                        history['priority_changes'].append({
                            'priority': change.get('priority'),
                            'changed_at': change.get('changed_at'),
                            'changed_by': change.get('changed_by'),
                            'comments': change.get('comments')
                        })

    return history
