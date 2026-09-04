"""
Company invitation endpoints: send an invitation, and list a company's
pending invitations with dedup/search/role-filter/sort/pagination.

Split from app/routes/companies.py (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2).

Stated exception: list_invitations is kept as a single ~200-line function.
Its dedup-by-most-recent-email-then-role-filter-then-paginate logic is one
cohesive query pipeline (three dependent subqueries feeding one result set)
and splitting it further would scatter that single dataflow across files
without making the module easier to reason about.
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, status, Request, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.user import User
from app.models.company import Company
from app.models.invitation import Invitation
from app.schemas.company import (
    UserInvitation,
    UserInvitationResponse,
    InvitationListResponse,
    InvitedByUser,
)

router = APIRouter()


@router.post("/{company_id}/invite", response_model=UserInvitationResponse)
async def invite_user(
    company_id: str,
    invitation: UserInvitation,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> UserInvitationResponse:
    """Invite a user to the company"""
    user = await get_current_user_required(request)

    # Check if user can invite to this company
    if user.company_id != company_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Can only invite users to your own company"
        )

    # Check if user is admin or has invite permissions
    if user.role not in ["admin", "manager"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions to invite users"
        )

    # Get company
    stmt = select(Company).where(Company.id == company_id)
    result = await db.execute(stmt)
    company = result.scalar_one_or_none()

    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company not found"
        )

    # Check if user already exists
    existing_user_stmt = select(User).where(User.email_id == invitation.email)
    existing_user_result = await db.execute(existing_user_stmt)
    existing_user = existing_user_result.scalar_one_or_none()

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User with this email already exists"
        )

    # Check if invitation already exists
    existing_invitation_stmt = select(Invitation).where(
        and_(
            Invitation.email == invitation.email,
            Invitation.company_id == company_id,
            Invitation.status == "pending"
        )
    )
    existing_invitation_result = await db.execute(existing_invitation_stmt)
    existing_invitation = existing_invitation_result.scalar_one_or_none()

    if existing_invitation:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invitation already exists for this email"
        )

    # Create invitation
    new_invitation = Invitation.create_invitation(
        email=invitation.email,
        role=invitation.role,
        company_id=company_id,
        invited_by=user.id,
        message=invitation.message
    )

    db.add(new_invitation)
    await db.commit()
    await db.refresh(new_invitation)

    # Create InvitedByUser object from the current user (include avatar_url for UI)
    invited_by_obj = InvitedByUser(
        userId=user.id,
        userEmail=user.email_id,
        username=user.name,
        avatar_url=user.avatar_url,
        role=user.role
    )

    # Create UserInvitationResponse with invited_by object
    return UserInvitationResponse(
        id=new_invitation.id,
        email=new_invitation.email,
        role=new_invitation.role,
        company_id=new_invitation.company_id,
        invited_by=invited_by_obj,
        status=new_invitation.status,
        message=new_invitation.message,
        created_at=new_invitation.created_at,
        expires_at=new_invitation.expires_at
    )


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
    """
    List company invitations with pagination, search, role filtering, and sorting.

    This endpoint retrieves a paginated list of pending invitations for a specific company.
    It supports searching by email, filtering by role, sorting by email or created_at,
    and provides comprehensive pagination metadata.

    Args:
        company_id: UUID of the company to list invitations from
        request: FastAPI request object for authentication
        db: Database session dependency
        page: Page number for pagination (default: 1)
        size: Number of items per page (default: 10, max: 100)
        search: Optional search term for filtering by email
        role: Optional role filter (e.g., admin, user, manager)
        sort_by: Field to sort by (email, created_at) - default: email
        sort_order: Sort direction (asc or desc) - default: asc

    Returns:
        InvitationListResponse: List of pending invitations with pagination metadata

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

    # Build base query with status filter for pending invitations
    # Step 1: Deduplicate by email first (get most recent invitation per email)
    # Step 2: Then apply role filter to the deduplicated results
    # Base conditions for deduplication (without role filter)
    dedup_conditions = [
        Invitation.company_id == company_id,
        Invitation.status == "pending"
    ]

    # Apply search filter if provided (for deduplication)
    if search:
        dedup_conditions.append(Invitation.email.ilike(f"%{search}%"))

    # Create subquery to get the most recent invitation per email (deduplication)
    dedup_subquery = (
        select(
            Invitation.id,
            Invitation.role,
            func.row_number()
            .over(
                partition_by=Invitation.email,
                order_by=Invitation.created_at.desc()
            )
            .label("rn")
        )
        .where(and_(*dedup_conditions))
    ).subquery()

    # Get only the most recent invitation per email (row_number = 1)
    distinct_invitation_ids_query = select(dedup_subquery.c.id).where(dedup_subquery.c.rn == 1)

    # Apply role filter AFTER deduplication if provided
    if role:
        distinct_invitation_ids_query = distinct_invitation_ids_query.where(dedup_subquery.c.role == role)

    # Build base query using the distinct invitation IDs (already filtered by role if provided)
    base_query = select(Invitation).where(Invitation.id.in_(distinct_invitation_ids_query))

    # Get total count - ALWAYS count overall distinct emails (without role filter)
    # This should not change based on filters
    total_count_subquery = (
        select(
            Invitation.email,
            func.row_number()
            .over(
                partition_by=Invitation.email,
                order_by=Invitation.created_at.desc()
            )
            .label("rn")
        )
        .where(
            and_(
                Invitation.company_id == company_id,
                Invitation.status == "pending"
            )
        )
    ).subquery()

    # Count distinct emails (overall total, not filtered)
    count_query = select(func.count()).select_from(
        total_count_subquery
    ).where(total_count_subquery.c.rn == 1)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Validate sort_by field
    allowed_sort_fields = ["email", "created_at"]
    if sort_by not in allowed_sort_fields:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid sort_by field. Allowed values: {', '.join(allowed_sort_fields)}"
        )

    # Validate sort_order
    if sort_order.lower() not in ["asc", "desc"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid sort_order. Allowed values: asc or desc"
        )

    # Apply sorting
    if sort_by == "email":
        if sort_order.lower() == "desc":
            data_query = base_query.order_by(Invitation.email.desc())
        else:
            data_query = base_query.order_by(Invitation.email.asc())
    else:  # Default: sort by created_at
        if sort_order.lower() == "desc":
            data_query = base_query.order_by(Invitation.created_at.desc())
        else:
            data_query = base_query.order_by(Invitation.created_at.asc())

    # Calculate pagination metadata
    total_pages = (total + size - 1) // size if total > 0 else 0  # Ceiling division
    has_next = page < total_pages
    has_previous = page > 1

    # Apply pagination
    data_query = data_query.offset((page - 1) * size).limit(size)

    # Execute query
    result = await db.execute(data_query)
    invitations = result.scalars().all()

    # Collect unique user IDs from invitations to fetch user data
    invited_by_user_ids = list(set([invitation.invited_by for invitation in invitations]))

    # Fetch all users who sent invitations in a single query
    users_query = select(User).where(User.id.in_(invited_by_user_ids))
    users_result = await db.execute(users_query)
    users = users_result.scalars().all()

    # Create a mapping of user_id -> user object for quick lookup
    users_map = {user.id: user for user in users}

    # Build invitation responses with invited_by user objects
    invitation_responses = []
    for invitation in invitations:
        # Get the user who sent the invitation
        invited_by_user = users_map.get(invitation.invited_by)

        # Create InvitedByUser object (include avatar_url for Admin Hub Invitations tab)
        if invited_by_user:
            invited_by_obj = InvitedByUser(
                userId=invited_by_user.id,
                userEmail=invited_by_user.email_id,
                username=invited_by_user.name,
                avatar_url=invited_by_user.avatar_url,
                role=invited_by_user.role
            )
        else:
            # Fallback if user not found (shouldn't happen, but handle gracefully)
            invited_by_obj = InvitedByUser(
                userId=invitation.invited_by,
                userEmail=None,
                username=None,
                avatar_url=None,
                role=None
            )

        # Create UserInvitationResponse with invited_by object
        invitation_response = UserInvitationResponse(
            id=invitation.id,
            email=invitation.email,
            role=invitation.role,
            company_id=invitation.company_id,
            invited_by=invited_by_obj,
            status=invitation.status,
            message=invitation.message,
            created_at=invitation.created_at,
            expires_at=invitation.expires_at
        )
        invitation_responses.append(invitation_response)

    return InvitationListResponse(
        invitations=invitation_responses,
        total=total,
        page=page,
        size=size,
        total_pages=total_pages,
        has_next=has_next,
        has_previous=has_previous
    )
