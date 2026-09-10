"""
Detail-building helpers for the task-list response path: build_task_details
and build_task_context. Split out of the former _details.py (Raven
style-compliance pass, see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md)
to keep both files under the 150-line target; load_task_details and
extract_task_history stayed behind in _details.py, while these two — used
only by _list_tasks_response.py's list-building path — moved here.
"""

from typing import Any, Dict

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.user import User
from app.models.task import Task
from app.models.workspace import Workspace
from app.models.channel import Channel
from app.models.message import Message, Thread

from ._shared import format_due_date_for_response


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
