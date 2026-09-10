"""
Profile route: remove_profile_photo.

Split out of the original monolithic profile.py (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5 follow-up).
"""

from datetime import datetime

from fastapi import APIRouter, HTTPException, status, Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required

from app.models.user import User

from app.schemas.user import ProfilePhotoRemoveResponse

router = APIRouter()


@router.delete("/profile/photo", response_model=ProfilePhotoRemoveResponse)
async def remove_profile_photo(
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> ProfilePhotoRemoveResponse:
    """
    Remove the current user's profile photo (set avatar_url to null).

    Requires authentication. After removal, the user's avatar_url is cleared in the database.
    """
    # Resolve current user (required)
    user = await get_current_user_required(request)
    # Load user in this session for update
    stmt = select(User).where(User.id == user.id)
    result = await db.execute(stmt)
    user_row = result.scalar_one_or_none()
    if not user_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    # Clear profile photo
    user_row.avatar_url = None
    user_row.updated_datetime = datetime.utcnow()
    await db.commit()
    return ProfilePhotoRemoveResponse(message="Profile photo removed successfully")
