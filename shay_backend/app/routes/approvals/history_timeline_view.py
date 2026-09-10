"""Timeline builder for GET /{approval_id}/history's response shape
(action/description/timestamp/user_id/user_name/status/details) — distinct
from history_builder.py's build_approval_history, which serves the list/
detail endpoints with a different shape (action/details/timestamp/user/
metadata) and resolves user objects via DB lookups. This view is purely
synchronous: it reads names/ids straight out of approval_metadata.
"""

from typing import Any, Dict, List

from app.models.approval import Approval


def build_history_view(approval: Approval) -> List[Dict[str, Any]]:
    """Build the comprehensive history list for GET /{approval_id}/history.

    Args:
        approval (Approval): The approval object.

    Returns:
        List[Dict[str, Any]]: History entries, sorted oldest-timestamp-string first.
    """
    history: List[Dict[str, Any]] = []

    # Add initial creation and assignment
    initial_assignment = None
    if approval.approval_metadata and 'initial_assignment' in approval.approval_metadata:
        initial_assignment = approval.approval_metadata['initial_assignment']

    if initial_assignment:
        history.append({
            "action": "assigned",
            "description": f"Assigned the approval to {initial_assignment.get('assigned_to_name', 'Unknown User')} and set the status to Pending Approval",
            "timestamp": initial_assignment.get('assigned_at', approval.created_at.isoformat() if approval.created_at else None),
            "user_id": initial_assignment.get('assigned_by'),
            "user_name": initial_assignment.get('assigned_by_name'),
            "status": "pending",
            "details": {
                "assigned_to": initial_assignment.get('assigned_to_name'),
                "title": approval.title,
                "description": approval.description
            }
        })
    else:
        # Fallback for older approvals without initial assignment tracking
        history.append({
            "action": "created",
            "description": f"Approval created and assigned to {approval.approver_user_id}",
            "timestamp": approval.created_at.isoformat() if approval.created_at else None,
            "user_id": str(approval.requested_by_user_id),
            "user_name": None,
            "status": "pending",
            "details": {
                "title": approval.title,
                "description": approval.description
            }
        })

    # Add reassignments
    if approval.approval_metadata and 'reassignments' in approval.approval_metadata:
        for reassignment in approval.approval_metadata['reassignments']:
            history.append({
                "action": "reassigned",
                "description": f"Assigned the approval to {reassignment.get('new_approver_name', 'Unknown User')} and set the status to Pending Approval",
                "timestamp": reassignment['reassigned_at'],
                "user_id": reassignment['reassigned_by'],
                "user_name": reassignment.get('reassigned_by_name'),
                "status": "pending",
                "details": {
                    "previous_approver": reassignment.get('previous_approver_name'),
                    "new_approver": reassignment.get('new_approver_name'),
                    "notes": reassignment.get('notes'),
                    "status_reset": reassignment.get('status_reset', False)
                }
            })

    # Add status changes
    if approval.approval_metadata and 'status_changes' in approval.approval_metadata:
        for status_change in approval.approval_metadata['status_changes']:
            if status_change.get('action_type') == 'reassignment_reset':
                continue  # Skip reassignment resets as they're covered in reassignments

            action_description = ""
            if status_change['new_status'] == 'approved':
                action_description = "Changed the approval status to Approved"
            elif status_change['new_status'] == 'rejected':
                action_description = "Changed the approval status to Rejected"
            elif status_change['new_status'] == 'pending':
                action_description = "Changed the approval status to Pending Approval"

            history.append({
                "action": "status_changed",
                "description": action_description,
                "timestamp": status_change['changed_at'],
                "user_id": status_change['changed_by'],
                "user_name": status_change.get('changed_by_name'),
                "status": status_change['new_status'],
                "details": {
                    "old_status": status_change['old_status'],
                    "new_status": status_change['new_status'],
                    "comment": status_change.get('comment'),
                    "rejection_reason": status_change.get('rejection_reason')
                }
            })

    # Sort history by timestamp
    history.sort(key=lambda x: x['timestamp'] or '')

    return history
