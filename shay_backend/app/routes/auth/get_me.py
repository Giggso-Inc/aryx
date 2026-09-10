"""
Get-current-user route: get_current_user_info (GET /me).

Split out of the original monolithic app/routes/auth.py (312 lines, over the
150-line hard limit) — see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md,
wave B5 (final wave). One endpoint per file, aggregated back into a single
`router` by app/routes/auth/__init__.py in the original registration order.
"""

from fastapi import APIRouter, Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.user import UserResponse

router = APIRouter()


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(request: Request, db: AsyncSession = Depends(get_db)) -> UserResponse:
    """Get current user information"""
    from app.middleware.auth_middleware import get_current_user_required

    user = await get_current_user_required(request)
    return UserResponse.from_orm(user)
