"""GET /count and GET /stats — approval counting and status statistics."""

from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.approval import Approval
from app.models.channel_member import ChannelMember
from app.models.message import Message
from app.schemas.approval import ApprovalCountResponse, ApprovalStats

router = APIRouter()


@router.get("/count", response_model=ApprovalCountResponse)
async def get_approval_count(
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> ApprovalCountResponse:
    """Get total count of approvals for the current user - uses same logic as list endpoint"""
    user = await get_current_user_required(request, db)

    # Get user's channel memberships (same logic as list_approvals endpoint)
    user_channels_stmt = select(ChannelMember.channel_id).where(
        and_(
            ChannelMember.user_id == user.id,
            ChannelMember.is_active == True
        )
    )
    user_channels_result = await db.execute(user_channels_stmt)
    user_channel_ids = [str(c) for c in user_channels_result.scalars().all()]

    # Build filters (same logic as list_approvals endpoint)
    filters = [Approval.is_active == "Y"]
    filters.append(Approval.message_id.isnot(None))  # Exclude orphan approvals
    # Default filtering: Only show approvals whose message is in user's channels
    if user_channel_ids:
        visible_msg_ids_stmt = select(Message.id).where(
            Message.channel_id.in_(user_channel_ids)
        )
        visible_msg_ids_result = await db.execute(visible_msg_ids_stmt)
        visible_message_ids = [row[0] for row in visible_msg_ids_result.all()]
        if visible_message_ids:
            filters.append(Approval.message_id.in_(visible_message_ids))
        else:
            return ApprovalCountResponse(approval_count=0)
    else:
        # If user is not a member of any channels, return 0 (same as list endpoint)
        return ApprovalCountResponse(approval_count=0)

    # Get total count using the same method as list endpoint
    count_query = select(func.count(Approval.id)).where(*filters)
    count_result = await db.execute(count_query)
    total_count = count_result.scalar() or 0

    return ApprovalCountResponse(approval_count=total_count)


@router.get("/stats", response_model=ApprovalStats)
async def get_approval_stats(
    request: Request,
    db: AsyncSession = Depends(get_db),
    channel_id: Optional[str] = Query(None, description="Filter by channel ID")
) -> ApprovalStats:
    """Get approval statistics."""
    user = await get_current_user_required(request, db)

    # Build base filters; exclude orphan approvals (no message_id)
    filters = [Approval.is_active == "Y", Approval.message_id.isnot(None)]

    if channel_id:
        # Resolve channel_id filter via message
        channel_msg_ids_stmt = select(Message.id).where(Message.channel_id == channel_id)
        channel_msg_ids_result = await db.execute(channel_msg_ids_stmt)
        channel_msg_ids = [row[0] for row in channel_msg_ids_result.all()]
        if channel_msg_ids:
            filters.append(Approval.message_id.in_(channel_msg_ids))
        else:
            filters.append(Approval.id == None)  # No results

    # Get counts for each status
    pending_query = select(func.count(Approval.id)).where(
        and_(*filters, Approval.status == "pending")
    )
    pending_result = await db.execute(pending_query)
    total_pending = pending_result.scalar() or 0

    approved_query = select(func.count(Approval.id)).where(
        and_(*filters, Approval.status == "approved")
    )
    approved_result = await db.execute(approved_query)
    total_approved = approved_result.scalar() or 0

    rejected_query = select(func.count(Approval.id)).where(
        and_(*filters, Approval.status == "rejected")
    )
    rejected_result = await db.execute(rejected_query)
    total_rejected = rejected_result.scalar() or 0

    total_query = select(func.count(Approval.id)).where(*filters)
    total_result = await db.execute(total_query)
    total_approvals = total_result.scalar() or 0

    return ApprovalStats(
        total_pending=total_pending,
        total_approved=total_approved,
        total_rejected=total_rejected,
        total_approvals=total_approvals
    )
