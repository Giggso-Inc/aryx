"""GET /{approval_id}/debug and GET /{approval_id}/history — raw metadata and rendered timeline."""

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.approval import Approval
from app.models.channel_member import ChannelMember
from app.models.message import Message

router = APIRouter()


@router.get("/{approval_id}/debug", response_model=Dict[str, Any])
async def debug_approval_metadata(
    approval_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """Debug endpoint to check raw approval metadata."""
    user = await get_current_user_required(request, db)

    # Get approval
    approval_stmt = select(Approval).where(Approval.id == approval_id)
    approval_result = await db.execute(approval_stmt)
    approval = approval_result.scalar_one_or_none()

    if not approval:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Approval not found"
        )

    return {
        "approval_id": str(approval.id),
        "status": approval.status,
        "approver_user_id": str(approval.approver_user_id),
        "raw_metadata": approval.approval_metadata,
        "metadata_type": type(approval.approval_metadata).__name__,
        "metadata_keys": list(approval.approval_metadata.keys()) if approval.approval_metadata else [],
        "reassignments_count": len(approval.approval_metadata.get('reassignments', [])) if approval.approval_metadata else 0,
        "status_changes_count": len(approval.approval_metadata.get('status_changes', [])) if approval.approval_metadata else 0
    }


@router.get("/{approval_id}/history", response_model=List[Dict[str, Any]])
async def get_approval_history(
    approval_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> List[Dict[str, Any]]:
    """Get comprehensive approval history including all actions and reassignments."""
    user = await get_current_user_required(request, db)

    # Get approval
    approval_stmt = select(Approval).where(Approval.id == approval_id)
    approval_result = await db.execute(approval_stmt)
    approval = approval_result.scalar_one_or_none()

    if not approval:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Approval not found"
        )

    # Check if user has access to this approval (must be requester, approver, or channel member)
    is_requester_hist = approval.requested_by_user_id and str(approval.requested_by_user_id) == str(user.id)
    is_approver_hist = approval.approver_user_id and str(approval.approver_user_id) == str(user.id)
    if not (is_requester_hist or is_approver_hist):
        channel_member = None
        if approval.message_id:
            msg_stmt = select(Message).where(Message.id == approval.message_id)
            msg_result = await db.execute(msg_stmt)
            msg = msg_result.scalar_one_or_none()
            if msg and msg.channel_id:
                channel_member_stmt = select(ChannelMember).where(
                    and_(
                        ChannelMember.channel_id == msg.channel_id,
                        ChannelMember.user_id == user.id,
                        ChannelMember.is_active == True
                    )
                )
                channel_member_result = await db.execute(channel_member_stmt)
                channel_member = channel_member_result.scalar_one_or_none()
        if not channel_member:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have access to this approval"
            )

    # Build comprehensive history
    history = []

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
