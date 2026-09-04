"""
GET /search — search_users_by_name_or_email.

Split out of the original app/routes/users.py (658 lines) as part of the
Raven style-compliance file-splitting pass (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2).
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.user import User
from app.schemas.user import UserResponse

router = APIRouter()


@router.get("/search", response_model=List[UserResponse])
async def search_users_by_name_or_email(
    name: Optional[str] = Query(None, description="Search by user name (partial match)"),
    email: Optional[str] = Query(None, description="Search by user email (exact match)"),
    request: Request = None,
    db: AsyncSession = Depends(get_db)
) -> List[UserResponse]:
    """
    Search for users by name or email across the system.

    This endpoint allows searching for users by either name (partial match) or email (exact match).
    At least one of the search parameters must be provided.

    Args:
        name: Optional name to search for (partial match using ILIKE)
        email: Optional email to search for (exact match)
        request: FastAPI request object for authentication
        db: Database session dependency

    Returns:
        List[UserResponse]: List of matching users

    Raises:
        HTTPException: 400 if no search parameters provided, 403 if access denied
    """
    # Check if at least one search parameter is provided
    if not name and not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one search parameter (name or email) must be provided"
        )

    # Build the search query
    query = select(User)

    if name and email:
        # Search by both name and email
        query = query.where(
            User.name.ilike(f"%{name}%") &
            User.email_id == email
        )
    elif name:
        # Search by name only (partial match)
        query = query.where(User.name.ilike(f"%{name}%"))
    elif email:
        # Search by email only (exact match)
        query = query.where(User.email_id == email)

    # Execute query
    result = await db.execute(query)
    users = result.scalars().all()

    return [UserResponse.from_orm(user) for user in users]
