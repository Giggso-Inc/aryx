"""POST /{approval_id}/reassign — reassign an approval, resetting status if it was completed."""

from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import attributes

from app.core.config import settings
from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.approval import Approval
from app.models.channel_member import ChannelMember
from app.models.message import Message
from app.models.user import User
from app.schemas.approval import ApprovalReassign, ApprovalResponse
from app.services.audit_service import log as audit_log_write
from app.services.link_shortener_service import link_shortener_service

from .notifications import process_approval_reassignment_notifications

router = APIRouter()


@router.post("/{approval_id}/reassign", response_model=ApprovalResponse)
async def reassign_approval(
    approval_id: str,
    reassign_data: ApprovalReassign,
    background_tasks: BackgroundTasks,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> ApprovalResponse:
    """Reassign an approval to another user.

    This endpoint allows reassignment of approvals in any status:
    - Pending approvals: Simple reassignment to new approver
    - Completed approvals (approved/rejected): Reassignment with status reset to pending
    """
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

    # Check if user can reassign this approval
    if str(approval.approver_user_id) != str(user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the assigned approver can reassign this approval"
        )

    # Allow reassignment of any approval status
    # If approval is completed (approved/rejected), reset status to pending
    was_completed = approval.status in ["approved", "rejected"]
    if was_completed:
        approval.status = "pending"
        # Clear completion timestamps when resetting to pending
        approval.approved_at = None
        approval.rejected_at = None
        approval.comment = None
        approval.rejection_reason = None

    # Resolve channel_id from message for channel membership checks
    reassign_channel_id = None
    reassign_thread_id = None
    if approval.message_id:
        msg_stmt = select(Message).where(Message.id == approval.message_id)
        msg_result = await db.execute(msg_stmt)
        msg = msg_result.scalar_one_or_none()
        if msg:
            reassign_channel_id = msg.channel_id
            reassign_thread_id = msg.thread_id

    # Validate new approver is a channel member (resolved via message)
    new_approver_member = None
    if reassign_channel_id:
        new_approver_member_stmt = select(ChannelMember).where(
            and_(
                ChannelMember.channel_id == reassign_channel_id,
                ChannelMember.user_id == reassign_data.new_approver_user_id,
                ChannelMember.is_active == True
            )
        )
        new_approver_member_result = await db.execute(new_approver_member_stmt)
        new_approver_member = new_approver_member_result.scalar_one_or_none()

    if reassign_channel_id and not new_approver_member:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New approver must be an active member of the channel"
        )

    # Store previous approver for history tracking
    previous_approver_id = approval.approver_user_id
    current_time = datetime.now(timezone.utc).replace(tzinfo=None)

    # Update approver
    approval.approver_user_id = reassign_data.new_approver_user_id
    approval.approval_notes = reassign_data.notes
    approval.updated_at = current_time

    # Get user information for tracking
    previous_approver_stmt = select(User).where(User.id == previous_approver_id)
    previous_approver_result = await db.execute(previous_approver_stmt)
    previous_approver = previous_approver_result.scalar_one_or_none()

    new_approver_stmt = select(User).where(User.id == reassign_data.new_approver_user_id)
    new_approver_result = await db.execute(new_approver_stmt)
    new_approver = new_approver_result.scalar_one_or_none()

    # Track reassignment in metadata
    if not approval.approval_metadata:
        approval.approval_metadata = {}

    if 'reassignments' not in approval.approval_metadata:
        approval.approval_metadata['reassignments'] = []

    # Track reassignment
    reassignment_entry = {
        'previous_approver_id': str(previous_approver_id),
        'new_approver_id': str(reassign_data.new_approver_user_id),
        'reassigned_by': str(user.id),
        'reassigned_at': current_time.isoformat(),
        'notes': reassign_data.notes,
        'previous_status': approval.status if not was_completed else 'pending',
        'status_reset': was_completed,
        'reset_reason': 'reassigned_completed_approval' if was_completed else None,
        'previous_approver_name': previous_approver.name if previous_approver else None,
        'new_approver_name': new_approver.name if new_approver else None,
        'reassigned_by_name': user.name if hasattr(user, 'name') else None
    }

    approval.approval_metadata['reassignments'].append(reassignment_entry)

    # Also track as a status change if status was reset
    if was_completed:
        if 'status_changes' not in approval.approval_metadata:
            approval.approval_metadata['status_changes'] = []

        approval.approval_metadata['status_changes'].append({
            'old_status': 'approved' if approval.status == 'pending' else 'rejected',
            'new_status': 'pending',
            'changed_by': str(user.id),
            'changed_at': current_time.isoformat(),
            'comment': f"Status reset to pending due to reassignment to {new_approver.name if new_approver else 'new approver'}",
            'rejection_reason': None,
            'action_type': 'reassignment_reset'
        })

    # Mark the JSONB field as modified so SQLAlchemy detects the change
    attributes.flag_modified(approval, 'approval_metadata')
    await audit_log_write(db, user.id, "approval.reassigned", "approval", approval.id, channel_id=approval.channel_id, thread_id=approval.thread_id, details={"new_approver_id": str(reassign_data.new_approver_user_id)})
    await db.commit()
    await db.refresh(approval)

    # Process approval reassignment notifications in background
    if reassign_channel_id and approval.approver_user_id and reassign_thread_id:
        # Use the canonical frontend root for real-time notifications.
        platform_url = settings.PLATFORM_URL

        # Construct redirect URL (shortened; store thread_id/channel_id for move-safe links)
        redirect_url = await link_shortener_service.shorten(
            f"{platform_url}/threads/{reassign_channel_id}/{reassign_thread_id}?openApproval=true", db,
            thread_id=reassign_thread_id, channel_id=reassign_channel_id, entity_type="approval",
        ) if platform_url else "#"
        # Construct notification settings URL (shortened; channel-level)
        notification_settings_url = await link_shortener_service.shorten(
            f"{platform_url}/threads/{reassign_channel_id}?openSettings=true&tab=notification", db,
            channel_id=reassign_channel_id, entity_type="channel",
        ) if platform_url else "#"

        background_tasks.add_task(
            process_approval_reassignment_notifications,
            str(user.id),  # Reassigner ID
            str(approval.approver_user_id),  # Reassigned approver ID
            str(reassign_channel_id),  # Channel ID
            redirect_url,  # Pre-constructed redirect URL
            notification_settings_url  # Pre-constructed notification settings URL
        )

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
