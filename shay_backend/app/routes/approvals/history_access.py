"""Access check for GET /{approval_id}/history — requester, approver, or
channel member may view an approval's history.
"""

from fastapi import HTTPException, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.approval import Approval
from app.models.channel_member import ChannelMember
from app.models.message import Message
from app.models.user import User


async def check_history_access(approval: Approval, user: User, db: AsyncSession) -> None:
    """Raise 403 unless the user is the requester, the approver, or a member
    of the channel the approval's message belongs to.

    Args:
        approval (Approval): The approval being viewed.
        user (User): The requesting user.
        db (AsyncSession): Database session.

    Raises:
        HTTPException: 403 if none of the access conditions are met.
    """
    is_requester_hist = approval.requested_by_user_id and str(approval.requested_by_user_id) == str(user.id)
    is_approver_hist = approval.approver_user_id and str(approval.approver_user_id) == str(user.id)
    if is_requester_hist or is_approver_hist:
        return

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
