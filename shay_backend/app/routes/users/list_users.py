"""
GET /company/{company_id}/users — list_company_users.

Split out of app/routes/users.py (658 lines); see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2.

Update (wave B4): the four company-wide count queries moved into
list_users_helpers.py (no dependency on base_query/data_query); the
paginated/non-paginated branches, which duplicated the same
UserListResponse construction, were unified into one branch that only
computes page/size/total_pages/has_next/has_previous differently -- same
values, same query executed, no behavior change.

Stated exception: sort_by/sort_order/status-param validation stays inline
-- see list_users_helpers.py's docstring: this function's own `status`
query parameter shadows the `fastapi.status` module for the whole
function body (pre-existing bug), so moving validation out would fix it.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.user import User
from app.schemas.user import UserListResponse, UserResponse
from .list_users_helpers import ALLOWED_SORT_FIELDS, _get_company_user_counts

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
    """List users in a company: search/role/active filters, sorting, and
    optional page+size pagination. Raises 403 if access denied, 400 if
    invalid parameters."""
    user = await get_current_user_required(request)
    # Check if user can access this company
    if not user.can_access_company(company_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )

    # Validate sort_by field
    if sort_by not in ALLOWED_SORT_FIELDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid sort_by field. Allowed values: {', '.join(ALLOWED_SORT_FIELDS)}"
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

    total, total_active, total_inactive, total_admin = await _get_company_user_counts(db, company_id)

    # Build query for data with sorting
    data_query = base_query
    sort_field = getattr(User, sort_by)
    if sort_order.lower() == "desc":
        data_query = data_query.order_by(sort_field.desc())
    else:
        data_query = data_query.order_by(sort_field.asc())

    # Determine if pagination is needed
    use_pagination = page is not None and size is not None

    if use_pagination:
        total_pages = (total + size - 1) // size  # Ceiling division
        has_next = page < total_pages
        has_previous = page > 1
        data_query = data_query.offset((page - 1) * size).limit(size)
    else:
        page = 1
        size = total
        total_pages = 1
        has_next = False
        has_previous = False

    result = await db.execute(data_query)
    users = result.scalars().all()

    return UserListResponse(
        users=[UserResponse.from_orm(u) for u in users],
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
