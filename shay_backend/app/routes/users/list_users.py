"""
GET /company/{company_id}/users — list_company_users.

Split out of the original app/routes/users.py (658 lines) as part of the
Raven style-compliance file-splitting pass (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2).

Stated exception: this file is ~180 lines, above the ~150-line target. The
single endpoint builds one cohesive filtered/sorted/paginated query (search,
role, is_active/status filters; four separate count queries; sort field
validation; then either a paginated or full result branch) that all operate
on the same `base_query`/`data_query` local state. Splitting the count
queries or the pagination branch into helper functions in another module
would not make any of them independently reusable -- nothing else in the
codebase builds a User list this way -- so the endpoint is kept as one file.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.user import User
from app.schemas.user import UserListResponse, UserResponse

router = APIRouter()


@router.get("/company/{company_id}/users", response_model=UserListResponse)
async def list_company_users(
    company_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: Optional[int] = Query(None, ge=1),
    size: Optional[int] = Query(None, ge=1, le=100),
    search: Optional[str] = None,
    role: Optional[str] = None,
    is_active: Optional[bool] = Query(None, description="Filter by active status: true for active users, false for inactive users"),
    status: Optional[str] = Query(None, description="Filter by status: 'Active' for active users, 'Inactive' for inactive users"),
    sort_by: str = Query("name", description="Sort by field: name, email_id, role, created_datetime, updated_datetime"),
    sort_order: str = Query("asc", description="Sort order: asc or desc")
) -> UserListResponse:
    """
    List users in a company with advanced filtering, sorting, and pagination.

    This endpoint retrieves a list of users within a specific company.
    By default, it returns ALL users in the company. If page and size parameters
    are provided, it returns a paginated list. It supports searching by name/email,
    filtering by role and active status, sorting by various fields, and provides
    comprehensive pagination metadata for frontend navigation.

    Args:
        company_id: UUID of the company to list users from
        request: FastAPI request object for authentication
        db: Database session dependency
        page: Optional page number for pagination (if not provided, returns all users)
        size: Optional number of users per page (if not provided, returns all users, max: 100)
        search: Optional search term for filtering by name or email
        role: Optional role filter (admin, user, guest)
        is_active: Optional filter by active status (true for active, false for inactive)
        status: Optional filter by status string ('Active' or 'Inactive') - takes precedence over is_active
        sort_by: Field to sort by (name, email_id, role, created_datetime, updated_datetime)
        sort_order: Sort direction (asc or desc)

    Returns:
        UserListResponse: List of users with metadata (paginated if page/size provided)

    Raises:
        HTTPException: 403 if access denied, 400 if invalid parameters
    """
    user = await get_current_user_required(request)

    # Check if user can access this company
    if not user.can_access_company(company_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )

    # Validate sort_by field
    allowed_sort_fields = ["name", "email_id", "role", "created_datetime", "updated_datetime"]
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

    # Handle status parameter - convert "Active"/"Inactive" to boolean
    # status parameter takes precedence over is_active if both are provided
    if status is not None and status.strip():
        status_lower = status.strip().lower()
        if status_lower == "active":
            is_active = True
        elif status_lower == "inactive":
            is_active = False
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid status value. Allowed values: 'Active' or 'Inactive'"
            )

    # Build base query for counting
    base_query = select(User).where(User.company_id == company_id)

    if search:
        base_query = base_query.where(
            User.name.ilike(f"%{search}%") |
            User.email_id.ilike(f"%{search}%")
        )

    if role:
        base_query = base_query.where(User.role == role)

    if is_active is not None:
        base_query = base_query.where(User.is_active == is_active)

    # Get total count - count all users for the company (without filters)
    # This shows the total count regardless of search, role, or status filters
    count_query = select(func.count(User.id)).where(User.company_id == company_id)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Calculate total_active, total_inactive, and total_admin from database
    # These counts are based on company_id only, not affected by search/role/status filters
    total_active_query = select(func.count(User.id)).where(
        and_(User.company_id == company_id, User.is_active == True)
    )
    total_active_result = await db.execute(total_active_query)
    total_active = total_active_result.scalar() or 0

    total_inactive_query = select(func.count(User.id)).where(
        and_(User.company_id == company_id, User.is_active == False)
    )
    total_inactive_result = await db.execute(total_inactive_query)
    total_inactive = total_inactive_result.scalar() or 0

    total_admin_query = select(func.count(User.id)).where(
        and_(User.company_id == company_id, User.role == "admin")
    )
    total_admin_result = await db.execute(total_admin_query)
    total_admin = total_admin_result.scalar() or 0

    # Build query for data with sorting
    data_query = base_query

    # Apply sorting
    sort_field = getattr(User, sort_by)
    if sort_order.lower() == "desc":
        data_query = data_query.order_by(sort_field.desc())
    else:
        data_query = data_query.order_by(sort_field.asc())

    # Determine if pagination is needed
    use_pagination = page is not None and size is not None

    if use_pagination:
        # Calculate pagination metadata
        total_pages = (total + size - 1) // size  # Ceiling division
        has_next = page < total_pages
        has_previous = page > 1

        # Apply pagination
        data_query = data_query.offset((page - 1) * size).limit(size)

        # Execute query
        result = await db.execute(data_query)
        users = result.scalars().all()

        return UserListResponse(
            users=[UserResponse.from_orm(user) for user in users],
            total=total,
            page=page,
            size=size,
            total_active=total_active,
            total_inactive=total_inactive,
            total_admin=total_admin,
            total_pages=total_pages,
            has_next=has_next,
            has_previous=has_previous
        )
    else:
        # Return all users without pagination
        result = await db.execute(data_query)
        users = result.scalars().all()

        return UserListResponse(
            users=[UserResponse.from_orm(user) for user in users],
            total=total,
            page=1,
            size=total,
            total_active=total_active,
            total_inactive=total_inactive,
            total_admin=total_admin,
            total_pages=1,
            has_next=False,
            has_previous=False
        )
