"""
GET /{company_id}/invitations — list_invitations: a company's pending
invitations with dedup/search/role-filter/sort/pagination.

Split from app/routes/companies.py (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2). invite_user
moved out to invite.py in wave B4, one endpoint per file.

Update (wave B4): the dedup query builder, sort validation/application, and
the total-count query moved into invitations_query.py; the invited-by
response assembly moved into invitations_response.py -- none of them share
state with each other beyond what's passed as arguments, so they were
genuinely separable. Call order is unchanged, which matters: characterized
behavior (see
tests/test_companies_characterization.py::TestListInvitations::
test_list_invitations_invalid_sort_by) is that the total-count query runs
BEFORE sort_by/sort_order are validated, so an invalid sort_by still 400s
only after that (redundant) query already executed once.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.schemas.company import InvitationListResponse
from .invitations_query import (
    _apply_invitation_sort,
    _build_distinct_invitation_query,
    _count_pending_invitations,
    _validate_invitation_sort,
)
from .invitations_response import _build_invitation_responses

router = APIRouter()


@router.get("/{company_id}/invitations", response_model=InvitationListResponse)
async def list_invitations(
    company_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1, description="Page number"),
    size: int = Query(10, ge=1, le=100, description="Number of items per page"),
    search: Optional[str] = Query(None, description="Search term for filtering by email"),
    role: Optional[str] = Query(None, description="Filter by role (e.g., admin, user, manager)"),
    sort_by: str = Query("email", description="Sort by field: email, created_at"),
    sort_order: str = Query("asc", description="Sort order: asc or desc")
) -> InvitationListResponse:
    """List a company's pending invitations: dedup by most-recent email,
    optional search/role filters, sorting, and pagination metadata.

    Raises:
        HTTPException: 403 if access denied, 400 if invalid sort parameters
    """
    user = await get_current_user_required(request)

    # Check if user can view invitations for this company
    if user.company_id != company_id and user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )

    base_query = _build_distinct_invitation_query(company_id, search, role)

    # Get total count - ALWAYS count overall distinct emails (without role
    # filter). Note: this executes before sort_by/sort_order validation
    # below -- see module docstring.
    total = await _count_pending_invitations(db, company_id)

    _validate_invitation_sort(sort_by, sort_order)

    data_query = _apply_invitation_sort(base_query, sort_by, sort_order)

    # Calculate pagination metadata
    total_pages = (total + size - 1) // size if total > 0 else 0  # Ceiling division
    has_next = page < total_pages
    has_previous = page > 1

    # Apply pagination
    data_query = data_query.offset((page - 1) * size).limit(size)

    # Execute query
    result = await db.execute(data_query)
    invitations = result.scalars().all()

    invitation_responses = await _build_invitation_responses(db, invitations)

    return InvitationListResponse(
        invitations=invitation_responses,
        total=total,
        page=page,
        size=size,
        total_pages=total_pages,
        has_next=has_next,
        has_previous=has_previous
    )
