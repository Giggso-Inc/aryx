"""
Detail-loading helpers: resolve a task's assigned/creator user objects and
its channel/workspace/thread context via its message_id. Used by crud.py,
listing.py, and thread_tasks.py.

Kept as one module (load_task_details, extract_task_history,
build_task_details, build_task_context): all four share the exact same
"select User/Message/Channel/Workspace by id, guard with hasattr/truthy
checks" pattern against the same models, and are always read together by
callers building a task response — splitting them apart would scatter that
one resolution pattern across files without isolating any independent
concern.
"""

from typing import Any, Dict, List

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.user import User
from app.models.task import Task
from app.models.workspace import Workspace
from app.models.channel import Channel
from app.models.message import Message, Thread

from ._shared import format_due_date_for_response


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


async def build_task_details(task: Task, db: AsyncSession) -> Dict[str, Any]:
    """Build detailed task information"""

    # Get assignee user details
    assignee_data = None
    if task.assigned_to:
        try:
            user_stmt = select(User).where(User.id == task.assigned_to)
            user_result = await db.execute(user_stmt)
            assignee_user = user_result.scalar_one_or_none()

            if assignee_user and hasattr(assignee_user, 'id'):
                assignee_data = {
                    'id': str(assignee_user.id),
                    'name': getattr(assignee_user, 'name', 'Unknown'),
                    'email_id': getattr(assignee_user, 'email_id', ''),
                    'avatar_url': getattr(assignee_user, 'avatar_url', ''),
                    'username': getattr(assignee_user, 'username', 'unknown')
                }

        except Exception as e:
            print(f"Error fetching assignee user: {e}")
            assignee_data = None

    # Get creator user details
    creator_data = None
    if task.created_by:
        try:
            creator_stmt = select(User).where(User.id == task.created_by)
            creator_result = await db.execute(creator_stmt)
            creator_user = creator_result.scalar_one_or_none()

            if creator_user and hasattr(creator_user, 'id'):
                creator_data = {
                    'id': str(creator_user.id),
                    'name': getattr(creator_user, 'name', 'Unknown'),
                    'email_id': getattr(creator_user, 'email_id', ''),
                    'avatar_url': getattr(creator_user, 'avatar_url', ''),
                    'username': getattr(creator_user, 'username', 'unknown')
                }

        except Exception as e:
            print(f"Error fetching creator user: {e}")
            creator_data = None

    return {
        'task_name': task.title,
        'status': task.status,
        'assignee': assignee_data,
        'created_by': creator_data,
        'priority': task.priority,
        'description': task.description,
        'due_date': format_due_date_for_response(task.due_date),
        'created_at': task.created_at,
        'updated_at': task.updated_at,
        'source': task.source,
        'tags': task.tags,
        'task_metadata': task.task_metadata
    }


async def build_task_context(task: Task, db: AsyncSession) -> Dict[str, Any]:
    """Build task context information by resolving through message_id"""
    context = {}

    if not (hasattr(task, 'message_id') and task.message_id):
        return context

    try:
        msg_stmt = select(Message).where(Message.id == task.message_id)
        msg_result = await db.execute(msg_stmt)
        msg = msg_result.scalar_one_or_none()

        if not msg:
            return context

        # Workspace context
        if msg.workspace_id:
            try:
                workspace_stmt = select(Workspace).where(Workspace.id == msg.workspace_id)
                workspace_result = await db.execute(workspace_stmt)
                workspace = workspace_result.scalar_one_or_none()
                if workspace and hasattr(workspace, 'id'):
                    context['workspace'] = {
                        'id': str(workspace.id),
                        'name': getattr(workspace, 'name', 'Unknown'),
                        'description': getattr(workspace, 'description', '')
                    }
            except Exception as e:
                print(f"Error fetching workspace context: {e}")

        # Channel context
        if msg.channel_id:
            try:
                channel_stmt = select(Channel).where(Channel.id == msg.channel_id)
                channel_result = await db.execute(channel_stmt)
                channel = channel_result.scalar_one_or_none()
                if channel and hasattr(channel, 'id'):
                    context['channel'] = {
                        'id': str(channel.id),
                        'name': getattr(channel, 'name', 'Unknown'),
                        'description': getattr(channel, 'description', ''),
                        'type': getattr(channel, 'type', 'unknown'),
                        'is_private': getattr(channel, 'is_private', False)
                    }
            except Exception as e:
                print(f"Error fetching channel context: {e}")

        # Thread context
        if msg.thread_id:
            try:
                thread_stmt = select(Thread).where(Thread.id == msg.thread_id)
                thread_result = await db.execute(thread_stmt)
                thread = thread_result.scalar_one_or_none()
                if thread and hasattr(thread, 'id'):
                    context['thread'] = {
                        'id': str(thread.id),
                        'title': getattr(thread, 'title', 'Unknown'),
                        'description': getattr(thread, 'description', '')
                    }
            except Exception as e:
                print(f"Error fetching thread context: {e}")

    except Exception as e:
        print(f"Error building task context from message: {e}")

    return context
