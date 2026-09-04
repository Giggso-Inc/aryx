"""GET /{approval_id} — fetch a single approval with resolved user/channel names."""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.approval import Approval
from app.models.channel import Channel
from app.models.channel_member import ChannelMember
from app.models.message import Message
from app.models.user import User
from app.schemas.approval import ApprovalWithDetailsResponse

router = APIRouter()


@router.get("/{approval_id}", response_model=ApprovalWithDetailsResponse)
async def get_approval(
    approval_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> ApprovalWithDetailsResponse:
    """Get a specific approval by ID."""
    user = await get_current_user_required(request, db)

    # Get approval with user details (channel_id/thread_id resolved via message_id)
    # Create aliases for the two user joins
    RequestedByUser = aliased(User)
    ApproverUser = aliased(User)

    approval_stmt = select(
        Approval,
        RequestedByUser.name.label('requested_by_user_name'),
        RequestedByUser.email_id.label('requested_by_user_email'),
        ApproverUser.name.label('approver_user_name'),
        ApproverUser.email_id.label('approver_user_email')
    ).join(
        RequestedByUser, Approval.requested_by_user_id == RequestedByUser.id, isouter=True
    ).join(
        ApproverUser, Approval.approver_user_id == ApproverUser.id, isouter=True
    ).where(Approval.id == approval_id)

    approval_result = await db.execute(approval_stmt)
    approval_data = approval_result.first()

    if not approval_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Approval not found"
        )

    approval, requested_by_name, requested_by_email, approver_name, approver_email = approval_data

    # Check if user has access to this approval (requester, approver, or channel member)
    is_requester = approval.requested_by_user_id and str(approval.requested_by_user_id) == str(user.id)
    is_approver = approval.approver_user_id and str(approval.approver_user_id) == str(user.id)
    if not (is_requester or is_approver):
        # Also allow channel members
        channel_member_access = False
        if approval.message_id:
            msg_stmt = select(Message).where(Message.id == approval.message_id)
            msg_result = await db.execute(msg_stmt)
            msg = msg_result.scalar_one_or_none()
            if msg and msg.channel_id:
                cm_stmt = select(ChannelMember).where(
                    and_(
                        ChannelMember.channel_id == msg.channel_id,
                        ChannelMember.user_id == user.id,
                        ChannelMember.is_active == True
                    )
                )
                cm_result = await db.execute(cm_stmt)
                channel_member_access = cm_result.scalar_one_or_none() is not None
        if not channel_member_access:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to this approval"
            )

    # Resolve channel_name for response via message
    channel_name = None
    if approval.message_id:
        msg_stmt = select(Message).where(Message.id == approval.message_id)
        msg_result = await db.execute(msg_stmt)
        msg = msg_result.scalar_one_or_none()
        if msg and msg.channel_id:
            ch_stmt = select(Channel).where(Channel.id == msg.channel_id)
            ch_result = await db.execute(ch_stmt)
            ch = ch_result.scalar_one_or_none()
            if ch:
                channel_name = ch.name

    return ApprovalWithDetailsResponse(
        id=str(approval.id),
        message_id=str(approval.message_id) if approval.message_id else None,
        channel_name=channel_name,
        requested_by_user_id=str(approval.requested_by_user_id) if approval.requested_by_user_id else None,
        requested_by_user_name=requested_by_name,
        requested_by_user_email=requested_by_email,
        approver_user_id=str(approval.approver_user_id) if approval.approver_user_id else None,
        approver_user_name=approver_name,
        approver_user_email=approver_email,
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
