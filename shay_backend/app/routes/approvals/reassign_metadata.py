"""Metadata bookkeeping for POST /{approval_id}/reassign — records the
reassignment (and any completed-status reset) into approval.approval_metadata.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import attributes

from app.models.approval import Approval
from app.models.user import User


def record_reassignment(
    approval: Approval,
    actor: User,
    previous_approver_id,
    previous_approver: Optional[User],
    new_approver: Optional[User],
    new_approver_user_id,
    notes: Optional[str],
    was_completed: bool,
    current_time: datetime,
) -> None:
    """Append a reassignment (and, if applicable, a status-reset) entry to
    approval.approval_metadata and flag the JSONB column as modified.

    Args:
        approval (Approval): The approval being reassigned (mutated in place).
        actor (User): The user performing the reassignment.
        previous_approver_id: The approver id being replaced, captured before
            approval.approver_user_id is overwritten by the caller.
        previous_approver (Optional[User]): The approver being replaced.
        new_approver (Optional[User]): The newly assigned approver.
        new_approver_user_id: The new approver's user id.
        notes (Optional[str]): Reassignment notes.
        was_completed (bool): Whether the approval's status was reset from a
            terminal state (approved/rejected) back to pending.
        current_time (datetime): Timestamp to record for this change.
    """
    if not approval.approval_metadata:
        approval.approval_metadata = {}

    if 'reassignments' not in approval.approval_metadata:
        approval.approval_metadata['reassignments'] = []

    reassignment_entry = {
        'previous_approver_id': str(previous_approver_id),
        'new_approver_id': str(new_approver_user_id),
        'reassigned_by': str(actor.id),
        'reassigned_at': current_time.isoformat(),
        'notes': notes,
        'previous_status': approval.status if not was_completed else 'pending',
        'status_reset': was_completed,
        'reset_reason': 'reassigned_completed_approval' if was_completed else None,
        'previous_approver_name': previous_approver.name if previous_approver else None,
        'new_approver_name': new_approver.name if new_approver else None,
        'reassigned_by_name': actor.name if hasattr(actor, 'name') else None
    }

    approval.approval_metadata['reassignments'].append(reassignment_entry)

    # Also track as a status change if status was reset
    if was_completed:
        if 'status_changes' not in approval.approval_metadata:
            approval.approval_metadata['status_changes'] = []

        approval.approval_metadata['status_changes'].append({
            'old_status': 'approved' if approval.status == 'pending' else 'rejected',
            'new_status': 'pending',
            'changed_by': str(actor.id),
            'changed_at': current_time.isoformat(),
            'comment': f"Status reset to pending due to reassignment to {new_approver.name if new_approver else 'new approver'}",
            'rejection_reason': None,
            'action_type': 'reassignment_reset'
        })

    # Mark the JSONB field as modified so SQLAlchemy detects the change
    attributes.flag_modified(approval, 'approval_metadata')
