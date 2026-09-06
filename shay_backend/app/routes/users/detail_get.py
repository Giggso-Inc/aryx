"""
GET /company/{company_id}/users/{user_id} — get_company_user.

Split out of the original app/routes/users.py (658 lines) as part of the
Raven style-compliance file-splitting pass (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2; further
split in wave B4 out of detail.py, one endpoint per file).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.user import User
from app.schemas.user import UserResponse

router = APIRouter()


@router.get("/company/{company_id}/users/{user_id}", response_model=UserResponse)
async def get_company_user(
    company_id: str,
    user_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> UserResponse:
    """Get a specific user in a company"""
    user = await get_current_user_required(request)

    # Check if user can access this company
    if not user.can_access_company(company_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )

    stmt = select(User).where(
        User.id == user_id,
        User.company_id == company_id
    )
    result = await db.execute(stmt)
    target_user = result.scalar_one_or_none()

    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    return UserResponse.from_orm(target_user)
