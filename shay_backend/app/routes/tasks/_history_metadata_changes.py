"""
task_metadata-driven history entries (status/priority/assignee changes) for
build_task_history. Split out of the former _history.py (Raven
style-compliance pass, see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md)
to keep both files under the 150-line target; the creation/assignment
entries stayed behind in _history.py.
"""

from datetime import datetime
from typing import Any, Dict, List

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.user import User
from app.models.task import Task


def _user_brief(change_user: User) -> Dict[str, Any]:
    return {
        'id': str(change_user.id),
        'name': getattr(change_user, 'name', 'Unknown'),
        'email_id': getattr(change_user, 'email_id', ''),
        'avatar_url': getattr(change_user, 'avatar_url', ''),
        'username': getattr(change_user, 'username', 'unknown')
    }


async def build_metadata_change_entries(task: Task, db: AsyncSession) -> List[Dict[str, Any]]:
    """Build the status/priority/assignee-change history entries recorded in
    task.task_metadata (mirrors the original inline sections 3-5)."""
    entries: List[Dict[str, Any]] = []
    metadata = task.task_metadata or {}

    for status_change in metadata.get('status_changes', []):
        change_user_stmt = select(User).where(User.id == status_change['changed_by'])
        change_user_result = await db.execute(change_user_stmt)
        change_user = change_user_result.scalar_one_or_none()

        if change_user and hasattr(change_user, 'id'):
            entries.append({
                'action': 'Status Changed',
                'details': f'Changed status to {status_change["status"]}',
                'timestamp': datetime.fromisoformat(status_change['changed_at'].replace('Z', '+00:00')).replace(tzinfo=None),
                'user': _user_brief(change_user),
                'metadata': {
                    'old_status': task.status,
                    'new_status': status_change['status'],
                    'comments': status_change.get('comments')
                }
            })

    for priority_change in metadata.get('priority_changes', []):
        change_user_stmt = select(User).where(User.id == priority_change['changed_by'])
        change_user_result = await db.execute(change_user_stmt)
        change_user = change_user_result.scalar_one_or_none()

        if change_user and hasattr(change_user, 'id'):
            entries.append({
                'action': 'Priority Changed',
                'details': f'Changed priority to {priority_change["priority"]}',
                'timestamp': datetime.fromisoformat(priority_change['changed_at'].replace('Z', '+00:00')).replace(tzinfo=None),
                'user': _user_brief(change_user),
                'metadata': {
                    'old_priority': task.priority,
                    'new_priority': priority_change['priority'],
                    'comments': priority_change.get('comments')
                }
            })

    for assignee_change in metadata.get('assignee_changes', []):
        change_user_stmt = select(User).where(User.id == assignee_change['changed_by'])
        change_user_result = await db.execute(change_user_stmt)
        change_user = change_user_result.scalar_one_or_none()

        previous_assignee_name = "Unknown"
        if assignee_change.get('previous_assignee'):
            prev_user_stmt = select(User).where(User.id == assignee_change['previous_assignee'])
            prev_user_result = await db.execute(prev_user_stmt)
            prev_user = prev_user_result.scalar_one_or_none()
            if prev_user:
                previous_assignee_name = getattr(prev_user, 'name', 'Unknown')

        new_assignee_name = "Unknown"
        if assignee_change.get('new_assignee'):
            new_user_stmt = select(User).where(User.id == assignee_change['new_assignee'])
            new_user_result = await db.execute(new_user_stmt)
            new_user = new_user_result.scalar_one_or_none()
            if new_user:
                new_assignee_name = getattr(new_user, 'name', 'Unknown')

        if change_user and hasattr(change_user, 'id'):
            entries.append({
                'action': 'Reassigned',
                'details': f'Reassigned from {previous_assignee_name} to {new_assignee_name}',
                'timestamp': datetime.fromisoformat(assignee_change['changed_at'].replace('Z', '+00:00')).replace(tzinfo=None),
                'user': _user_brief(change_user),
                'metadata': {
                    'previous_assignee': assignee_change.get('previous_assignee'),
                    'new_assignee': assignee_change.get('new_assignee'),
                    'action': assignee_change.get('action', 'reassigned')
                }
            })

    return entries
