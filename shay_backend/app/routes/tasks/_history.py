"""
Task history timeline builder, used by listing.py's list_tasks endpoint.

Kept as its own single-function module (176 lines, over the 150-line
target): build_task_history is inherently one long function because it
appends five sequential, order-dependent sections (creation, assignment,
status changes, priority changes, assignee changes) to the same running
`history` list before a final sort — splitting it into five helper
functions would only move the same list-building logic behind five extra
call sites with no independent reuse.
"""

from datetime import timedelta
from typing import Any, Dict, List

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.user import User
from app.models.task import Task

from ._details import load_task_details
from ._shared import format_due_date_for_response


async def build_task_history(task: Task, db: AsyncSession) -> List[Dict[str, Any]]:
    """Build task history timeline"""
    history = []

    # Simple approach: Always add basic task creation and assignment history
    # This ensures we always have some history even if user lookups fail

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
        # Get task details to get user information
        task_details = await load_task_details(task, db)
        assignee_user = task_details.get('assigned_user')
        creator_user = task_details.get('created_by')

        # Update task creation with user details if available
        if creator_user:
            history[0]['details'] = f'Task "{task.title}" created by {creator_user.get("name", "Unknown")}'
            history[0]['user'] = creator_user

        # Add assignment history if we have assignee
        if assignee_user:
            due_date_info = ""
            if task.due_date:
                # Handle both date and datetime objects
                if hasattr(task.due_date, 'strftime'):
                    due_date_info = f" Due: {task.due_date.strftime('%m-%d-%Y %I:%M %p')}"
                else:
                    # For date objects, add default time
                    from datetime import datetime
                    dt = datetime.combine(task.due_date, datetime.min.time())
                    due_date_info = f" Due: {dt.strftime('%m-%d-%Y %I:%M %p')}"

            # Use a slightly later timestamp for assignment to appear first
            assignment_timestamp = task.created_at
            if hasattr(task, 'created_at') and task.created_at:
                # Add 1 second to make assignment appear before task creation
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

    # 3. Status changes from metadata
    if task.task_metadata and 'status_changes' in task.task_metadata:
        for status_change in task.task_metadata['status_changes']:
            # Get user who made the change
            change_user_stmt = select(User).where(User.id == status_change['changed_by'])
            change_user_result = await db.execute(change_user_stmt)
            change_user = change_user_result.scalar_one_or_none()

            if change_user and hasattr(change_user, 'id'):
                from datetime import datetime
                history.append({
                    'action': 'Status Changed',
                    'details': f'Changed status to {status_change["status"]}',
                    'timestamp': datetime.fromisoformat(status_change['changed_at'].replace('Z', '+00:00')).replace(tzinfo=None),
                    'user': {
                        'id': str(change_user.id),
                        'name': getattr(change_user, 'name', 'Unknown'),
                        'email_id': getattr(change_user, 'email_id', ''),
                        'avatar_url': getattr(change_user, 'avatar_url', ''),
                        'username': getattr(change_user, 'username', 'unknown')
                    },
                    'metadata': {
                        'old_status': task.status,
                        'new_status': status_change['status'],
                        'comments': status_change.get('comments')
                    }
                })

    # 4. Priority changes (if any)
    if task.task_metadata and 'priority_changes' in task.task_metadata:
        for priority_change in task.task_metadata['priority_changes']:
            change_user_stmt = select(User).where(User.id == priority_change['changed_by'])
            change_user_result = await db.execute(change_user_stmt)
            change_user = change_user_result.scalar_one_or_none()

            if change_user and hasattr(change_user, 'id'):
                history.append({
                    'action': 'Priority Changed',
                    'details': f'Changed priority to {priority_change["priority"]}',
                    'timestamp': datetime.fromisoformat(priority_change['changed_at'].replace('Z', '+00:00')).replace(tzinfo=None),
                    'user': {
                        'id': str(change_user.id),
                        'name': getattr(change_user, 'name', 'Unknown'),
                        'email_id': getattr(change_user, 'email_id', ''),
                        'avatar_url': getattr(change_user, 'avatar_url', ''),
                        'username': getattr(change_user, 'username', 'unknown')
                    },
                    'metadata': {
                        'old_priority': task.priority,
                        'new_priority': priority_change['priority'],
                        'comments': priority_change.get('comments')
                    }
                })

    # 5. Assignee changes (reassignments)
    if task.task_metadata and 'assignee_changes' in task.task_metadata:
        for assignee_change in task.task_metadata['assignee_changes']:
            # Get user who made the change
            change_user_stmt = select(User).where(User.id == assignee_change['changed_by'])
            change_user_result = await db.execute(change_user_stmt)
            change_user = change_user_result.scalar_one_or_none()

            # Get previous assignee details
            previous_assignee_name = "Unknown"
            if assignee_change.get('previous_assignee'):
                prev_user_stmt = select(User).where(User.id == assignee_change['previous_assignee'])
                prev_user_result = await db.execute(prev_user_stmt)
                prev_user = prev_user_result.scalar_one_or_none()
                if prev_user:
                    previous_assignee_name = getattr(prev_user, 'name', 'Unknown')

            # Get new assignee details
            new_assignee_name = "Unknown"
            if assignee_change.get('new_assignee'):
                new_user_stmt = select(User).where(User.id == assignee_change['new_assignee'])
                new_user_result = await db.execute(new_user_stmt)
                new_user = new_user_result.scalar_one_or_none()
                if new_user:
                    new_assignee_name = getattr(new_user, 'name', 'Unknown')

            if change_user and hasattr(change_user, 'id'):
                from datetime import datetime
                history.append({
                    'action': 'Reassigned',
                    'details': f'Reassigned from {previous_assignee_name} to {new_assignee_name}',
                    'timestamp': datetime.fromisoformat(assignee_change['changed_at'].replace('Z', '+00:00')).replace(tzinfo=None),
                    'user': {
                        'id': str(change_user.id),
                        'name': getattr(change_user, 'name', 'Unknown'),
                        'email_id': getattr(change_user, 'email_id', ''),
                        'avatar_url': getattr(change_user, 'avatar_url', ''),
                        'username': getattr(change_user, 'username', 'unknown')
                    },
                    'metadata': {
                        'previous_assignee': assignee_change.get('previous_assignee'),
                        'new_assignee': assignee_change.get('new_assignee'),
                        'action': assignee_change.get('action', 'reassigned')
                    }
                })

    # Sort history by timestamp (newest first)
    history.sort(key=lambda x: x['timestamp'], reverse=True)

    return history
