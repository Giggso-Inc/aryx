"""
Update-current-user route: update_current_user (PUT /me).

Split out of the original monolithic app/routes/auth.py (312 lines, over the
150-line hard limit) — see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md,
wave B5 (final wave). One endpoint per file, aggregated back into a single
`router` by app/routes/auth/__init__.py in the original registration order.
"""

from fastapi import APIRouter, Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.auth import UserUpdate
from app.schemas.user import UserResponse

router = APIRouter()


@router.put("/me", response_model=UserResponse)
async def update_current_user(
    user_update: UserUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> UserResponse:
    """Update current user information"""
    from app.middleware.auth_middleware import get_current_user_required

    user = await get_current_user_required(request)

    # Update user fields
    update_data = user_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(user, field, value)

    await db.commit()
    await db.refresh(user)

    return UserResponse.from_orm(user)
