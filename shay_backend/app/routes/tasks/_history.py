"""
Task history timeline builder, used by _list_tasks_response.py's list-of-
tasks response path.

Split out of the original (199-line) _history.py (Raven style-compliance
pass, see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md): the
metadata-driven status/priority/assignee-change sections moved to
_history_metadata_changes.py, leaving build_task_history itself as a thin
orchestrator — build creation+assignment entries, append the
metadata-driven ones, sort.
"""

from datetime import timedelta, datetime
from typing import Any, Dict, List

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import Task

from ._details import load_task_details
from ._shared import format_due_date_for_response
from ._history_metadata_changes import build_metadata_change_entries


async def build_task_history(task: Task, db: AsyncSession) -> List[Dict[str, Any]]:
    """Build task history timeline"""
    history = []

    # 1. Task creation (always add)
    creation_timestamp = task.created_at
    if hasattr(task, 'created_at') and task.created_at:
        # Subtract 1 second to make task creation appear after assignment
        creation_timestamp = task.created_at - timedelta(seconds=1)

    history.append({
        'action': 'Task Created',
        'details': f'Task "{task.title}" created',
        'timestamp': creation_timestamp,
        'user': None,
        'metadata': {
            'priority': task.priority,
            'source': task.source or 'manual'
        }
    })

    # 2. Task assignment (always add if we can get user details)
    try:
        task_details = await load_task_details(task, db)
        assignee_user = task_details.get('assigned_user')
        creator_user = task_details.get('created_by')

        if creator_user:
            history[0]['details'] = f'Task "{task.title}" created by {creator_user.get("name", "Unknown")}'
            history[0]['user'] = creator_user

        if assignee_user:
            due_date_info = ""
            if task.due_date:
                if hasattr(task.due_date, 'strftime'):
                    due_date_info = f" Due: {task.due_date.strftime('%m-%d-%Y %I:%M %p')}"
                else:
                    dt = datetime.combine(task.due_date, datetime.min.time())
                    due_date_info = f" Due: {dt.strftime('%m-%d-%Y %I:%M %p')}"

            # Use a slightly later timestamp for assignment to appear first
            assignment_timestamp = task.created_at
            if hasattr(task, 'created_at') and task.created_at:
                assignment_timestamp = task.created_at + timedelta(seconds=1)

            history.append({
                'action': 'Assigned to',
                'details': f'Assigned to {assignee_user.get("name", "Unknown")}@{assignee_user.get("username", "unknown")}{due_date_info} Priority: {task.priority}',
                'timestamp': assignment_timestamp,
                'user': assignee_user,
                'metadata': {
                    'priority': task.priority,
                    'due_date': format_due_date_for_response(task.due_date)
                }
            })

    except Exception as e:
        print(f"Error getting user details for task history: {e}")
        # Keep the basic history we already created

    # 3-5. Status/priority/assignee changes recorded in task_metadata
    history.extend(await build_metadata_change_entries(task, db))

    # Sort history by timestamp (newest first)
    history.sort(key=lambda x: x['timestamp'], reverse=True)

    return history
