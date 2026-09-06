"""Base query + filter construction for GET / list_approvals, before pagination.

Split out of list.py's single list_approvals function: this is the
query-building half (visibility scoping via channel membership, then the
optional status/creator/assignee/my-* filters), independent from the
per-row response building and the two pagination strategies.
"""

from typing import Optional

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.approval import Approval
from app.models.channel_member import ChannelMember
from app.models.message import Message
from app.models.user import User
from app.utils.channel_access import check_channel_access_by_thread


async def build_approval_list_query(
    user: User,
    db: AsyncSession,
    channel_id: Optional[str],
    thread_id: Optional[str],
    status_filter: Optional[str],
    created_by: Optional[str],
    assigned_to: Optional[str],
    my_approvals: bool,
    my_requests: bool,
):
    """Build the filtered, sorted base_query for list_approvals.

    Returns:
        tuple: (base_query, filters) — filters is also reused unmodified for
            the total-count query in the non requested_by pagination path.
    """
    RequestedByUser = aliased(User)
    ApproverUser = aliased(User)

    base_query = select(
        Approval,
        RequestedByUser.name.label('requested_by_user_name'),
        RequestedByUser.email_id.label('requested_by_user_email'),
        ApproverUser.name.label('approver_user_name'),
        ApproverUser.email_id.label('approver_user_email')
    ).join(
        RequestedByUser, Approval.requested_by_user_id == RequestedByUser.id, isouter=True
    ).join(
        ApproverUser, Approval.approver_user_id == ApproverUser.id, isouter=True
    )

    # Apply filters
    filters = [Approval.is_active == "Y"]
    # Exclude orphan approvals (no message_id)
    filters.append(Approval.message_id.isnot(None))

    # Default filtering: Only show approvals whose message belongs to channels where user is a member
    user_channels_stmt = select(ChannelMember.channel_id).where(
        and_(
            ChannelMember.user_id == user.id,
            ChannelMember.is_active == True
        )
    )
    user_channels_result = await db.execute(user_channels_stmt)
    user_channel_ids = [str(c) for c in user_channels_result.scalars().all()]

    if user_channel_ids:
        visible_msg_ids_stmt = select(Message.id).where(
            Message.channel_id.in_(user_channel_ids)
        )
        if channel_id:
            visible_msg_ids_stmt = visible_msg_ids_stmt.where(Message.channel_id == channel_id)
        if thread_id:
            await check_channel_access_by_thread(db, user, thread_id)
            visible_msg_ids_stmt = visible_msg_ids_stmt.where(Message.thread_id == thread_id)
        visible_msg_ids_result = await db.execute(visible_msg_ids_stmt)
        visible_message_ids = [row[0] for row in visible_msg_ids_result.all()]
        if visible_message_ids:
            filters.append(Approval.message_id.in_(visible_message_ids))
        else:
            filters.append(Approval.id == None)  # No results
    else:
        # If user is not a member of any channels, return empty result
        filters.append(Approval.id == None)

    # Multi-status filtering
    if status_filter:
        status_list = [s.strip() for s in status_filter.split(',') if s.strip()]
        if status_list:
            filters.append(Approval.status.in_(status_list))

    if created_by:
        filters.append(Approval.requested_by_user_id == created_by)

    if assigned_to:
        filters.append(Approval.approver_user_id == assigned_to)

    # Note: requested_by filter is applied by the caller after building
    # approval details, because it requires checking reassignments metadata

    if my_approvals:
        filters.append(Approval.approver_user_id == user.id)

    if my_requests:
        filters.append(Approval.requested_by_user_id == user.id)

    base_query = base_query.where(*filters)
    base_query = base_query.order_by(Approval.created_at.desc())

    return base_query, filters
