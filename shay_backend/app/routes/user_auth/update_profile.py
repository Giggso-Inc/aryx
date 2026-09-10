"""
Profile route: update_current_user_personal_info.

Split out of the original monolithic profile.py (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5 follow-up).
"""

from datetime import datetime

from fastapi import APIRouter, HTTPException, status, Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db

from app.models.user import User

from app.schemas.user import ProfileUpdateRequest, ProfileUpdateResponse

from app.routes.user_auth._profile_helpers import _build_user_profile_dict

router = APIRouter()


@router.put("/profile", response_model=ProfileUpdateResponse)
async def update_current_user_personal_info(
    profile_update: ProfileUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> ProfileUpdateResponse:
    """
    Update current user's personal information only.

    Allows authenticated users to update only their personal information
    (name, avatar URL, preferences). Sensitive fields (email, role, company
    association, system-related fields) cannot be changed here.

    Args:
        profile_update: ProfileUpdateRequest containing personal fields to update
        request: FastAPI request object for authentication
        db: Database session dependency

    Returns:
        ProfileUpdateResponse: message, list of updated_fields, and the
        updated user profile dict (same shape as GET /profile).

    Raises:
        HTTPException: 401 if not authenticated, 404 if user not found,
        400 if a field is not allowed or has the wrong type.

    Author: Pranhav Vimalbalaji
    Version: 1.0.0
    Last date modified: 19/08/2025
    """
    # Get current user from request state
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Query user in current database session
    stmt = select(User).where(User.id == user_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # Define allowed fields for personal information updates (avatar_url may be None to remove photo)
    allowed_fields = {
        "name": str,
        "avatar_url": (str, type(None)),  # str or None to clear profile photo
        "preferences": dict
    }

    # Convert Pydantic model to dict and filter update data
    profile_update_dict = profile_update.model_dump(exclude_unset=True)
    update_data = {}
    updated_fields = []

    for field, value in profile_update_dict.items():
        if field in allowed_fields:
            # Type validation (allow None for avatar_url to remove profile photo)
            allowed_types = allowed_fields[field]
            if not isinstance(allowed_types, tuple):
                allowed_types = (allowed_types,)
            if isinstance(value, allowed_types):
                update_data[field] = value
                updated_fields.append(field)
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid type for field '{field}'."
                )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Field '{field}' is not allowed for personal information updates"
            )

    # Apply updates
    if update_data:
        for field, value in update_data.items():
            if hasattr(user, field):
                setattr(user, field, value)

        # Update the updated_datetime field
        user.updated_datetime = datetime.utcnow()

        await db.commit()
        await db.refresh(user)

    return ProfileUpdateResponse(
        message="Profile updated successfully",
        updated_fields=updated_fields,
        user=_build_user_profile_dict(user)
    )
