"""
GET / — list approvals with filtering and pagination.

Originally a single ~290-line function combining query-building, two
mutually-exclusive pagination strategies, and per-row response building
(duplicated verbatim in each branch). Split into list_query.py (filtered
base query) and list_row.py (per-row EnhancedApprovalResponse + its
try/except fallback, now shared instead of duplicated). This file keeps only
the endpoint's own concern: choosing between and running the two pagination
strategies. See docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md.
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.approval import Approval
from app.schemas.approval import ApprovalListResponse

from .list_query import build_approval_list_query
from .list_row import build_basic_enhanced_approval, build_enhanced_approval, resolve_approval_details

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

    base_query, filters = await build_approval_list_query(
        user, db, channel_id, thread_id, status_filter, created_by, assigned_to, my_approvals, my_requests
    )

    # Handle requested_by filter differently due to pagination requirements
    if requested_by:
        # For requested_by filter, we need to get all matching records first,
        # then apply pagination to avoid missing results across pages
        all_items_result = await db.execute(base_query)
        all_rows = all_items_result.all()

        all_approvals = []
        for approval, *_ in all_rows:
            approval_details, used_fallback = await resolve_approval_details(approval, db)

            # Check if this approval matches the requested_by filter
            requested_by_user = approval_details.get('requested_by')
            if not (requested_by_user and requested_by_user.get('id') == requested_by):
                continue

            if used_fallback:
                all_approvals.append(build_basic_enhanced_approval(approval, approval_details))
            else:
                all_approvals.append(await build_enhanced_approval(approval, approval_details, db))

        # Apply pagination to the filtered results
        total = len(all_approvals)
        offset = (page - 1) * size
        approvals = all_approvals[offset:offset + size]

    else:
        # Normal flow for other filters
        offset = (page - 1) * size
        items_query = base_query.offset(offset).limit(size)
        items_result = await db.execute(items_query)
        rows = items_result.all()

        count_query = select(func.count(Approval.id)).where(*filters)
        count_result = await db.execute(count_query)
        total = count_result.scalar()

        approvals = []
        for approval, *_ in rows:
            approval_details, used_fallback = await resolve_approval_details(approval, db)
            if used_fallback:
                approvals.append(build_basic_enhanced_approval(approval, approval_details))
            else:
                approvals.append(await build_enhanced_approval(approval, approval_details, db))

    has_more = (page * size) < total

    return ApprovalListResponse(
        approvals=approvals,
        total=total,
        page=page,
        size=size,
        has_more=has_more
    )
