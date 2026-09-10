"""PUT /{approval_id} — update a pending approval's title/description/approver."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.approval import Approval
from app.models.channel_member import ChannelMember
from app.models.message import Message
from app.schemas.approval import ApprovalResponse, ApprovalUpdate
from app.services.audit_service import log as audit_log_write

router = APIRouter()


@router.put("/{approval_id}", response_model=ApprovalResponse)
async def update_approval(
    approval_id: str,
    approval_data: ApprovalUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> ApprovalResponse:
    """Update an approval request (only pending approvals can be updated)."""
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

    # Check if user can update this approval
    if not (str(approval.requested_by_user_id) == str(user.id) or
            str(approval.approver_user_id) == str(user.id)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to update this approval"
        )

    # Only pending approvals can be updated
    if approval.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only pending approvals can be updated"
        )

    # Update fields
    if approval_data.title is not None:
        approval.title = approval_data.title

    if approval_data.description is not None:
        approval.description = approval_data.description

    # If changing approver, validate the new approver is a channel member (resolved via message)
    if approval_data.approver_user_id is not None:
        update_channel_id = None
        if approval.message_id:
            msg_stmt = select(Message).where(Message.id == approval.message_id)
            msg_result = await db.execute(msg_stmt)
            msg = msg_result.scalar_one_or_none()
            if msg:
                update_channel_id = msg.channel_id

        if update_channel_id:
            new_approver_member_stmt = select(ChannelMember).where(
                and_(
                    ChannelMember.channel_id == update_channel_id,
                    ChannelMember.user_id == approval_data.approver_user_id,
                    ChannelMember.is_active == True
                )
            )
            new_approver_member_result = await db.execute(new_approver_member_stmt)
            new_approver_member = new_approver_member_result.scalar_one_or_none()

            if not new_approver_member:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="New approver must be an active member of the channel"
                )

        approval.approver_user_id = approval_data.approver_user_id

    approval.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)

    await audit_log_write(db, user.id, "approval.updated", "approval", approval.id, channel_id=approval.channel_id, thread_id=approval.thread_id)
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
