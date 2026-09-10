"""POST /{approval_id}/reassign — reassign an approval, resetting status if it was completed."""

from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.approval import Approval
from app.models.channel_member import ChannelMember
from app.models.message import Message
from app.models.user import User
from app.schemas.approval import ApprovalReassign, ApprovalResponse
from app.services.audit_service import log as audit_log_write

from .approval_response import to_approval_response
from .notification_links import build_notification_urls
from .notifications_reassigned_process import process_approval_reassignment_notifications
from .reassign_metadata import record_reassignment

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

    # Track reassignment (and status-reset, if applicable) in metadata
    record_reassignment(
        approval, user, previous_approver_id, previous_approver, new_approver,
        reassign_data.new_approver_user_id, reassign_data.notes, was_completed, current_time,
    )

    await audit_log_write(db, user.id, "approval.reassigned", "approval", approval.id, channel_id=approval.channel_id, thread_id=approval.thread_id, details={"new_approver_id": str(reassign_data.new_approver_user_id)})
    await db.commit()
    await db.refresh(approval)

    # Process approval reassignment notifications in background
    if reassign_channel_id and approval.approver_user_id and reassign_thread_id:
        redirect_url, notification_settings_url = await build_notification_urls(
            reassign_channel_id, reassign_thread_id, db
        )

        background_tasks.add_task(
            process_approval_reassignment_notifications,
            str(user.id),  # Reassigner ID
            str(approval.approver_user_id),  # Reassigned approver ID
            str(reassign_channel_id),  # Channel ID
            redirect_url,  # Pre-constructed redirect URL
            notification_settings_url  # Pre-constructed notification settings URL
        )

    return to_approval_response(approval)
