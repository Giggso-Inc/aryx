"""Initial-assignment timeline entry for build_approval_history — one block
of app/routes/approvals/history_builder.py's original single function,
extracted as a genuine seam (it operates on its own metadata key and has its
own legacy fallback branch, independent of reassignments/status_changes).
"""

from datetime import timedelta
from typing import Any, Dict, List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.approval import Approval
from app.models.user import User

from .details import load_approval_details


def _user_summary(user: User) -> Dict[str, Any]:
    return {
        'id': str(user.id),
        'name': user.name,
        'email_id': user.email_id,
        'avatar_url': user.avatar_url,
        'username': user.name or 'unknown'
    }


async def build_initial_assignment_entries(approval: Approval, metadata: Dict[str, Any], db: AsyncSession) -> List[Dict[str, Any]]:
    """Build the 'creation'/'assigned to' timeline entry (or its legacy
    fallback) for build_approval_history.

    Args:
        approval (Approval): The approval object.
        metadata (Dict[str, Any]): approval.approval_metadata (or {}).
        db (AsyncSession): Database session.

    Returns:
        List[Dict[str, Any]]: Zero, one, or two history entries.
    """
    history: List[Dict[str, Any]] = []

    initial_assignment = metadata.get('initial_assignment') if metadata else None

    if initial_assignment:
        assigned_by_user = None
        if initial_assignment.get('assigned_by'):
            user_stmt = select(User).where(User.id == initial_assignment['assigned_by'])
            user_result = await db.execute(user_stmt)
            user = user_result.scalar_one_or_none()
            if user:
                assigned_by_user = _user_summary(user)

        if assigned_by_user:
            assigned_at = None
            if initial_assignment.get('assigned_at'):
                try:
                    assigned_at = datetime_fromisoformat(initial_assignment['assigned_at'])
                except Exception:
                    assigned_at = approval.created_at
            else:
                assigned_at = approval.created_at

            history.append({
                'action': 'Assigned to',
                'details': f'Assigned the approval to {initial_assignment.get("assigned_to_name", "Unknown User")}@{initial_assignment.get("assigned_to_name", "unknown")} and set the status to Pending Approval',
                'timestamp': assigned_at,
                'user': assigned_by_user,
                'metadata': {
                    'assigned_to': initial_assignment.get('assigned_to_name'),
                    'title': approval.title,
                    'description': approval.description
                }
            })
    else:
        # Fallback for older approvals without initial assignment tracking
        user_details = await load_approval_details(approval, db)
        requester_user = user_details.get('requested_by_user')
        approver_user = user_details.get('approver_user')

        if requester_user:
            history.append({
                'action': 'Approval Created',
                'details': f'Approval "{approval.title}" created by {requester_user["name"]}',
                'timestamp': approval.created_at - timedelta(seconds=1),  # Ensure it appears first
                'user': requester_user,
                'metadata': {
                    'title': approval.title,
                    'description': approval.description
                }
            })

        if approver_user:
            history.append({
                'action': 'Assigned to',
                'details': f'Assigned the approval to {approver_user["name"]}@{approver_user.get("username", "unknown")} and set the status to Pending Approval',
                'timestamp': approval.created_at + timedelta(seconds=1),  # Ensure it appears after creation
                'user': approver_user,
                'metadata': {
                    'status': approval.status
                }
            })

    return history


def datetime_fromisoformat(value: str):
    """Parse an ISO timestamp, stripping tzinfo (metadata timestamps are stored naive)."""
    from datetime import datetime
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo:
        parsed = parsed.replace(tzinfo=None)
    return parsed
