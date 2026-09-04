"""
GET / — list approvals with filtering and pagination.

Stated exception to the 150-line target: list_approvals is a single
~290-line function with two mutually-exclusive pagination strategies (the
`requested_by` filter needs to fetch all rows and paginate in Python
because the filter depends on reassignment metadata, not a DB column,
while every other filter combination paginates in SQL). It was
golden-mastered as one unit; splitting the two branches into separate
helpers would duplicate most of the filter-building logic above them for
no behavior change. Kept together per the Raven Style Compliance Plan's
"too tightly coupled to split further safely" carve-out (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.approval import Approval
from app.models.channel_member import ChannelMember
from app.models.message import Message
from app.models.user import User
from app.schemas.approval import (
    ApprovalDetails,
    ApprovalHistoryItem,
    ApprovalListResponse,
    EnhancedApprovalResponse,
)
from app.utils.channel_access import check_channel_access_by_thread

from .details import build_approval_details
from .history_builder import build_approval_context, build_approval_history

router = APIRouter()


@router.get("/", response_model=ApprovalListResponse)
async def list_approvals(
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    status_filter: Optional[str] = Query(None, description="Filter by status(es): pending, approved, rejected (comma-separated for multiple)"),
    channel_id: Optional[str] = Query(None, description="Filter by channel ID"),
    thread_id: Optional[str] = Query(None, description="Filter by thread ID"),
    created_by: Optional[str] = Query(None, description="Filter by user ID who created the approval"),
    assigned_to: Optional[str] = Query(None, description="Filter by user ID who is assigned to approve"),
    requested_by: Optional[str] = Query(None, description="Filter by user ID who last requested approval to somebody"),
    my_approvals: bool = Query(False, description="Show only approvals assigned to current user"),
    my_requests: bool = Query(False, description="Show only approvals requested by current user")
) -> ApprovalListResponse:
    """
    List approvals with filtering and pagination.

    This endpoint retrieves a paginated list of approvals with optional filtering.
    It supports filtering by status, channel, thread, creator, assignee, requester, and user-specific views.

    Args:
        request (Request): FastAPI request object for authentication
        db (AsyncSession): Database session for data operations
        page (int): Page number (1-based)
        size (int): Number of items per page (1-100)
        status_filter (Optional[str]): Filter by approval status(es) - comma-separated for multiple
        channel_id (Optional[str]): Filter by specific channel ID
        thread_id (Optional[str]): Filter by specific thread ID
        created_by (Optional[str]): Filter by user ID who created the approval
        assigned_to (Optional[str]): Filter by user ID who is assigned to approve
        requested_by (Optional[str]): Filter by user ID who last requested approval to somebody
        my_approvals (bool): Show only approvals assigned to current user
        my_requests (bool): Show only approvals requested by current user

    Returns:
        ApprovalListResponse: Paginated list of approvals with enhanced details, history, and context

    Raises:
        HTTPException: 401 if user not authenticated
    """
    user = await get_current_user_required(request, db)

    # Build base query with joins for user details
    # channel_id/thread_id are no longer on Approval; resolved via message_id
    # Create aliases for the two user joins
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
    # Get user's channel memberships
    user_channels_stmt = select(ChannelMember.channel_id).where(
        and_(
            ChannelMember.user_id == user.id,
            ChannelMember.is_active == True
        )
    )
    user_channels_result = await db.execute(user_channels_stmt)
    user_channel_ids = [str(c) for c in user_channels_result.scalars().all()]

    if user_channel_ids:
        # Find message IDs in user's channels
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
        filters.append(Approval.id == None)  # This will return no results

    # Multi-status filtering
    if status_filter:
        status_list = [s.strip() for s in status_filter.split(',') if s.strip()]
        if status_list:
            filters.append(Approval.status.in_(status_list))

    # Note: channel_id/thread_id filters already applied above via message resolution

    if created_by:
        filters.append(Approval.requested_by_user_id == created_by)

    if assigned_to:
        filters.append(Approval.approver_user_id == assigned_to)

    # Note: requested_by filter will be applied after building approval details
    # because it requires checking reassignments metadata

    if my_approvals:
        filters.append(Approval.approver_user_id == user.id)

    if my_requests:
        filters.append(Approval.requested_by_user_id == user.id)

    # Apply filters to base query
    base_query = base_query.where(*filters)

    # Add sorting (newest first)
    base_query = base_query.order_by(Approval.created_at.desc())

    # Handle requested_by filter differently due to pagination requirements
    if requested_by:
        # For requested_by filter, we need to get all matching records first,
        # then apply pagination to avoid missing results across pages

        # Get all approvals without pagination
        all_items_query = base_query
        all_items_result = await db.execute(all_items_query)
        all_rows = all_items_result.all()

        # Build enhanced response with history and context for all records
        all_approvals = []
        for approval, requested_by_name, requested_by_email, approver_name, approver_email in all_rows:
            try:
                # Refresh approval to get latest data
                await db.refresh(approval)

                # Build approval details
                approval_details = await build_approval_details(approval, db)

                # Check if this approval matches the requested_by filter
                requested_by_user = approval_details.get('requested_by')
                if requested_by_user and requested_by_user.get('id') == requested_by:
                    # Build approval history
                    approval_history = await build_approval_history(approval, db)

                    # Build context
                    context = await build_approval_context(approval, db)

                    # Create enhanced approval response
                    enhanced_approval = EnhancedApprovalResponse(
                        id=str(approval.id),
                        approval_details=ApprovalDetails(**approval_details),
                        approval_history=[ApprovalHistoryItem(**item) for item in approval_history],
                        context=context
                    )
                    all_approvals.append(enhanced_approval)

            except Exception as e:
                print(f"Error building approval details for {approval.id}: {e}")
                print(f"Approval status: {approval.status}")
                print(f"Approval metadata: {approval.approval_metadata}")
                import traceback
                traceback.print_exc()

                # Fallback to basic response
                approval_details = {
                    'approval_name': approval.title,
                    'status': approval.status,
                    'approver': None,
                    'created_by': None,
                    'requested_by': None,
                    'title': approval.title,
                    'description': approval.description,
                    'approval_notes': approval.approval_notes,
                    'rejection_reason': approval.rejection_reason,
                    'comment': approval.comment,
                    'created_at': approval.created_at,
                    'updated_at': approval.updated_at,
                    'approved_at': approval.approved_at,
                    'rejected_at': approval.rejected_at,
                    'approval_metadata': approval.approval_metadata or {}
                }

                # Check if this approval matches the requested_by filter
                requested_by_user = approval_details.get('requested_by')
                if requested_by_user and requested_by_user.get('id') == requested_by:
                    enhanced_approval = EnhancedApprovalResponse(
                        id=str(approval.id),
                        approval_details=ApprovalDetails(**approval_details),
                        approval_history=[],
                        context={}
                    )
                    all_approvals.append(enhanced_approval)

        # Apply pagination to the filtered results
        total = len(all_approvals)
        offset = (page - 1) * size
        approvals = all_approvals[offset:offset + size]

    else:
        # Normal flow for other filters
        # Apply pagination
        offset = (page - 1) * size
        items_query = base_query.offset(offset).limit(size)
        items_result = await db.execute(items_query)
        rows = items_result.all()

        # Get total count
        count_query = select(func.count(Approval.id)).where(*filters)
        count_result = await db.execute(count_query)
        total = count_result.scalar()

        # Build enhanced response with history and context
        approvals = []
        for approval, requested_by_name, requested_by_email, approver_name, approver_email in rows:
            try:
                # Refresh approval to get latest data
                await db.refresh(approval)

                # Build approval details
                approval_details = await build_approval_details(approval, db)

                # Build approval history
                approval_history = await build_approval_history(approval, db)

                # Build context
                context = await build_approval_context(approval, db)

                # Create enhanced approval response
                enhanced_approval = EnhancedApprovalResponse(
                    id=str(approval.id),
                    approval_details=ApprovalDetails(**approval_details),
                    approval_history=[ApprovalHistoryItem(**item) for item in approval_history],
                    context=context
                )
                approvals.append(enhanced_approval)

            except Exception as e:
                print(f"Error building approval details for {approval.id}: {e}")
                print(f"Approval status: {approval.status}")
                print(f"Approval metadata: {approval.approval_metadata}")
                import traceback
                traceback.print_exc()

                # Fallback to basic response
                approval_details = {
                    'approval_name': approval.title,
                    'status': approval.status,
                    'approver': None,
                    'created_by': None,
                    'requested_by': None,
                    'title': approval.title,
                    'description': approval.description,
                    'approval_notes': approval.approval_notes,
                    'rejection_reason': approval.rejection_reason,
                    'comment': approval.comment,
                    'created_at': approval.created_at,
                    'updated_at': approval.updated_at,
                    'approved_at': approval.approved_at,
                    'rejected_at': approval.rejected_at,
                    'approval_metadata': approval.approval_metadata or {}
                }

                enhanced_approval = EnhancedApprovalResponse(
                    id=str(approval.id),
                    approval_details=ApprovalDetails(**approval_details),
                    approval_history=[],
                    context={}
                )
                approvals.append(enhanced_approval)

    has_more = (page * size) < total

    return ApprovalListResponse(
        approvals=approvals,
        total=total,
        page=page,
        size=size,
        has_more=has_more
    )
