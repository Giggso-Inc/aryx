"""Validation helpers for POST / create_approval — message/thread/approver checks."""

from fastapi import HTTPException, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.approval import Approval
from app.models.channel_member import ChannelMember
from app.models.message import Message, Thread
from app.models.user import User
from app.schemas.approval import ApprovalCreate


async def load_and_validate_create_target(approval_data: ApprovalCreate, db: AsyncSession):
    """
    Resolve and validate the message/thread/approver for a new approval request.

    Args:
        approval_data (ApprovalCreate): The incoming approval request payload.
        db (AsyncSession): Database session for data operations.

    Returns:
        tuple: (message, thread, thread_id, approver_user) — approver_user may be
            None if the approver id doesn't resolve to a User row.

    Raises:
        HTTPException: 404 if message/thread not found, 400 if the message doesn't
            belong to the thread or the approver isn't an active channel member,
            409 if the thread already has a pending approval.
    """
    message_stmt = select(Message).where(Message.id == approval_data.message_id)
    message_result = await db.execute(message_stmt)
    message = message_result.scalar_one_or_none()

    if not message:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message not found"
        )

    # Use provided thread_id or auto-detect from message
    thread_id = approval_data.thread_id or str(message.thread_id)

    thread_stmt = select(Thread).where(Thread.id == thread_id)
    thread_result = await db.execute(thread_stmt)
    thread = thread_result.scalar_one_or_none()

    if not thread:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Thread not found"
        )

    if str(message.thread_id) != thread_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Message does not belong to the specified thread"
        )

    approver_member_stmt = select(ChannelMember).where(
        and_(
            ChannelMember.channel_id == thread.channel_id,
            ChannelMember.user_id == approval_data.approver_user_id,
            ChannelMember.is_active == True
        )
    )
    approver_member_result = await db.execute(approver_member_stmt)
    approver_member = approver_member_result.scalar_one_or_none()

    if not approver_member:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Approver must be an active member of the channel"
        )

    # Check if there's already an active approval for this thread (via message IDs in thread)
    thread_msg_ids_stmt = select(Message.id).where(Message.thread_id == thread_id)
    thread_msg_ids_result = await db.execute(thread_msg_ids_stmt)
    thread_msg_ids = [row[0] for row in thread_msg_ids_result.all()]

    if thread_msg_ids:
        existing_approval_stmt = select(Approval).where(
            and_(
                Approval.message_id.in_(thread_msg_ids),
                Approval.is_active == "Y",
                Approval.status == "pending"
            )
        )
        existing_approval_result = await db.execute(existing_approval_stmt)
        existing_approval = existing_approval_result.scalar_one_or_none()

        if existing_approval:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="There is already a pending approval for this thread"
            )

    # Get approver user information for tracking
    approver_user_stmt = select(User).where(User.id == approval_data.approver_user_id)
    approver_user_result = await db.execute(approver_user_stmt)
    approver_user = approver_user_result.scalar_one_or_none()

    return message, thread, thread_id, approver_user
