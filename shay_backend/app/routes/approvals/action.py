"""POST /{approval_id}/action — approve or reject a pending approval."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import attributes

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.approval import Approval
from app.schemas.approval import ApprovalAction, ApprovalResponse

router = APIRouter()


@router.post("/{approval_id}/action", response_model=ApprovalResponse)
async def take_approval_action(
    approval_id: str,
    action_data: ApprovalAction,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> ApprovalResponse:
    """Take action on an approval (approve/reject)."""
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

    # Check if user can take action on this approval
    if str(approval.approver_user_id) != str(user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the assigned approver can take action on this approval"
        )

    # Only pending approvals can have actions taken
    if approval.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only pending approvals can have actions taken"
        )

    # Validate action
    if action_data.action not in ["approve", "reject"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Action must be either 'approve' or 'reject'"
        )

    # Store old status for history tracking
    old_status = approval.status
    current_time = datetime.now(timezone.utc).replace(tzinfo=None)

    # Update approval based on action
    if action_data.action == "approve":
        approval.status = "approved"
        approval.comment = action_data.comment
        approval.approved_at = current_time
    else:  # reject
        approval.status = "rejected"
        approval.comment = action_data.comment
        approval.rejection_reason = action_data.rejection_reason
        approval.rejected_at = current_time

    approval.updated_at = current_time

    # Track status change in metadata
    if not approval.approval_metadata:
        approval.approval_metadata = {}

    if 'status_changes' not in approval.approval_metadata:
        approval.approval_metadata['status_changes'] = []

    approval.approval_metadata['status_changes'].append({
        'old_status': old_status,
        'new_status': approval.status,
        'changed_by': str(user.id),
        'changed_by_name': user.name if hasattr(user, 'name') else None,
        'changed_at': current_time.isoformat(),
        'comment': action_data.comment,
        'rejection_reason': action_data.rejection_reason if action_data.action == "reject" else None,
        'action_type': 'status_change'
    })

    # Mark the JSONB field as modified so SQLAlchemy detects the change
    attributes.flag_modified(approval, 'approval_metadata')

    await db.commit()
    await db.refresh(approval)

    # Convert UUID fields to strings for the response
    return ApprovalResponse(
        id=str(approval.id),
        message_id=str(approval.message_id) if approval.message_id else None,
        requested_by_user_id=str(approval.requested_by_user_id) if approval.requested_by_user_id else None,
        approver_user_id=str(approval.approver_user_id) if approval.approver_user_id else None,
        status=approval.status,
        title=approval.title,
        description=approval.description,
        approval_notes=approval.approval_notes,
        rejection_reason=approval.rejection_reason,
        comment=approval.comment,
        is_active=approval.is_active,
        created_at=approval.created_at,
        updated_at=approval.updated_at,
        approved_at=approval.approved_at,
        rejected_at=approval.rejected_at
    )
