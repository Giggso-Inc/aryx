"""Reassignment and status-change timeline entries for build_approval_history
— the other two independent metadata blocks split out of the original
single-function history_builder.py (each operates on its own metadata key
and is order-independent before the final sort).
"""

from datetime import datetime
from typing import Any, Dict, List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.approval import Approval
from app.models.user import User


def _user_summary(user: User) -> Dict[str, Any]:
    return {
        'id': str(user.id),
        'name': user.name,
        'email_id': user.email_id,
        'avatar_url': user.avatar_url,
        'username': user.name or 'unknown'
    }


def _parse_timestamp(value, fallback: datetime) -> datetime:
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
            if parsed.tzinfo:
                parsed = parsed.replace(tzinfo=None)
            return parsed
        except Exception:
            return fallback
    return fallback


async def build_reassignment_entries(approval: Approval, metadata: Dict[str, Any], db: AsyncSession) -> List[Dict[str, Any]]:
    """Build one timeline entry per recorded reassignment.

    Args:
        approval (Approval): The approval object.
        metadata (Dict[str, Any]): approval.approval_metadata (or {}).
        db (AsyncSession): Database session.

    Returns:
        List[Dict[str, Any]]: One entry per reassignment with a resolvable actor.
    """
    history: List[Dict[str, Any]] = []

    for reassignment in (metadata.get('reassignments') if metadata else None) or []:
        reassigned_by_user = None
        if reassignment.get('reassigned_by'):
            user_stmt = select(User).where(User.id == reassignment['reassigned_by'])
            user_result = await db.execute(user_stmt)
            user = user_result.scalar_one_or_none()
            if user:
                reassigned_by_user = _user_summary(user)

        if reassigned_by_user:
            reassigned_at = _parse_timestamp(reassignment.get('reassigned_at'), approval.updated_at)

            history.append({
                'action': 'Reassigned',
                'details': f'Assigned the approval to {reassignment.get("new_approver_name", "Unknown User")}@{reassignment.get("new_approver_name", "unknown")} and set the status to Pending Approval',
                'timestamp': reassigned_at,
                'user': reassigned_by_user,
                'metadata': {
                    'previous_approver': reassignment.get('previous_approver_name'),
                    'new_approver': reassignment.get('new_approver_name'),
                    'notes': reassignment.get('notes'),
                    'status_reset': reassignment.get('status_reset', False)
                }
            })

    return history


async def build_status_change_entries(approval: Approval, metadata: Dict[str, Any], db: AsyncSession) -> List[Dict[str, Any]]:
    """Build one timeline entry per recorded status change, skipping the
    'reassignment_reset' action type (already covered by reassignment entries).

    Args:
        approval (Approval): The approval object.
        metadata (Dict[str, Any]): approval.approval_metadata (or {}).
        db (AsyncSession): Database session.

    Returns:
        List[Dict[str, Any]]: One entry per status change with a resolvable actor.
    """
    history: List[Dict[str, Any]] = []

    for status_change in (metadata.get('status_changes') if metadata else None) or []:
        if status_change.get('action_type') == 'reassignment_reset':
            continue  # Skip reassignment resets as they're covered in reassignments

        changed_by_user = None
        if status_change.get('changed_by'):
            user_stmt = select(User).where(User.id == status_change['changed_by'])
            user_result = await db.execute(user_stmt)
            user = user_result.scalar_one_or_none()
            if user:
                changed_by_user = _user_summary(user)

        if changed_by_user:
            changed_at = _parse_timestamp(status_change.get('changed_at'), approval.updated_at)

            action_description = ""
            if status_change['new_status'] == 'approved':
                action_description = "Changed the approval status to Approved"
            elif status_change['new_status'] == 'rejected':
                action_description = "Changed the approval status to Rejected"
            elif status_change['new_status'] == 'pending':
                action_description = "Changed the approval status to Pending Approval"

            history.append({
                'action': 'Status Changed',
                'details': action_description,
                'timestamp': changed_at,
                'user': changed_by_user,
                'metadata': {
                    'old_status': status_change.get('old_status'),
                    'new_status': status_change['new_status'],
                    'comment': status_change.get('comment'),
                    'rejection_reason': status_change.get('rejection_reason')
                }
            })

    return history
