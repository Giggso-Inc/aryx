"""
Profile routes: get_current_user_profile_details, upload_profile_image,
remove_profile_photo, update_current_user_personal_info.

Split out of the original monolithic app/routes/user_auth.py (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5).

Note: `update_current_user_personal_info` is ~150 lines including its
docstring; it stays here rather than getting its own submodule since it is
tightly coupled to the other profile endpoints (same allowed-field pattern,
same response shape) — a stated exception to the ~150-line-per-file target.
"""

import os
from datetime import datetime

from fastapi import APIRouter, HTTPException, status, Request, Depends, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.services.file_storage import get_file_storage_service

from app.models.user import User

from app.schemas.user import (
    ProfileUpdateRequest, ProfileUpdateResponse, ProfileImageUploadResponse, ProfilePhotoRemoveResponse,
)

router = APIRouter()


@router.get("/profile", response_model=dict)
async def get_current_user_profile_details(
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> dict:
    """
    Get current user's detailed profile information.

    This endpoint retrieves the authenticated user's profile details with
    personal information, role, and preferences.

    Args:
        request: FastAPI request object for authentication
        db: Database session dependency

    Returns:
        dict: Current user's detailed profile information

    Raises:
        HTTPException: 401 if not authenticated

    Sample Response Schema:
    {
        "id": "uuid-string",
        "name": "John Doe",
        "email_id": "john.doe@example.com",
        "avatar_url": "https://example.com/avatar.jpg",
        "role": "senior_developer",
        "is_active": true,
        "is_verified": true,
        "oauth_provider": "local",
        "preferences": {
            "theme": "dark",
            "language": "en",
            "notifications": true
        },
        "last_login": "2025-01-20T10:30:00Z",
        "created_datetime": "2025-01-15T09:00:00Z",
        "updated_datetime": "2025-01-20T10:30:00Z"
    }

    Author: Pranhav Vimalbalaji
    Version: 1.0.0
    Last date modified: 20/01/2025
    """
    user = await get_current_user_required(request)

    # Build user profile response
    user_profile = {
        "id": str(user.id),
        "name": user.name,
        "email_id": user.email_id,
        "avatar_url": user.avatar_url,
        "role": user.role,
        "is_active": user.is_active,
        "is_verified": user.is_verified,
        "oauth_provider": user.oauth_provider,
        "preferences": user.preferences,
        "last_login": user.last_login,
        "created_datetime": user.created_datetime,
        "updated_datetime": user.updated_datetime
    }

    return user_profile


# Allowed image extensions for profile avatar upload
PROFILE_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
# Max size for profile image (5MB)
MAX_PROFILE_IMAGE_SIZE_BYTES = 5 * 1024 * 1024


@router.post("/profile/upload-image", response_model=ProfileImageUploadResponse)
async def upload_profile_image(
    file: UploadFile = File(..., description="Profile image file (jpg, png, gif, webp)"),
    request: Request = None,
    db: AsyncSession = Depends(get_db)
) -> ProfileImageUploadResponse:
    """
    Upload a profile image for the current user.
    Returns the avatar_url to use in PUT /profile (avatar_url field).
    After upload, call PUT /profile with { "avatar_url": "<returned avatar_url>" } to save it to the profile.
    """
    user = await get_current_user_required(request)
    # Validate file extension
    file_ext = os.path.splitext(file.filename or "")[1].lower()
    if file_ext not in PROFILE_IMAGE_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid file type. Allowed: {', '.join(PROFILE_IMAGE_EXTENSIONS)}"
        )
    content = await file.read()
    # Validate size
    if len(content) > MAX_PROFILE_IMAGE_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File too large. Maximum size is {MAX_PROFILE_IMAGE_SIZE_BYTES // (1024*1024)}MB"
        )
    # Build storage path: profile/{user_id}/avatar_{timestamp}.ext
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    destination_path = f"profile/{user.id}/avatar_{timestamp}{file_ext}"
    try:
        storage_service = get_file_storage_service()
        upload_result = await storage_service.upload_file(
            file_content=content,
            destination_path=destination_path,
            original_filename=file.filename or "avatar"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload profile image: {str(e)}"
        )
    return ProfileImageUploadResponse(
        avatar_url=upload_result["file_url"],
        message="Profile image uploaded successfully"
    )


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


@router.put("/profile", response_model=ProfileUpdateResponse)
async def update_current_user_personal_info(
    profile_update: ProfileUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> ProfileUpdateResponse:
    """
    Update current user's personal information only.

    This endpoint allows authenticated users to update only their personal
    information such as name, avatar URL, and preferences. Users cannot
    change sensitive fields like email, role, company association, or
    system-related fields.

    Args:
        profile_update: ProfileUpdateRequest containing personal fields to update
        request: FastAPI request object for authentication
        db: Database session dependency

    Returns:
        dict: Updated user profile information

    Raises:
        HTTPException: 401 if not authenticated, 400 if invalid data

    Sample Request Schema:
    {
        "name": "John Smith",
        "avatar_url": "https://example.com/new-avatar.jpg",
        "preferences": {
            "theme": "light",
            "language": "en",
            "notifications": true,
            "timezone": "UTC-8",
            "date_format": "MM/DD/YYYY"
        }
    }

    Sample Response Schema:
    {
        "message": "Profile updated successfully",
        "updated_fields": ["name", "avatar_url", "preferences"],
        "user": {
            "id": "uuid-string",
            "name": "John Smith",
            "email_id": "john.doe@example.com",
            "avatar_url": "https://example.com/new-avatar.jpg",
            "role": "senior_developer",
            "is_active": true,
            "is_verified": true,
            "oauth_provider": "local",
            "preferences": {
                "theme": "light",
                "language": "en",
                "notifications": true,
                "timezone": "UTC-8",
                "date_format": "MM/DD/YYYY"
            },
            "last_login": "2025-01-20T10:30:00Z",
            "created_datetime": "2025-01-15T09:00:00Z",
            "updated_datetime": "2025-01-20T11:45:00Z"
        }
    }

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

    # Build response
    user_profile = {
        "id": str(user.id),
        "name": user.name,
        "email_id": user.email_id,
        "avatar_url": user.avatar_url,
        "role": user.role,
        "is_active": user.is_active,
        "is_verified": user.is_verified,
        "oauth_provider": user.oauth_provider,
        "preferences": user.preferences,
        "last_login": user.last_login,
        "created_datetime": user.created_datetime,
        "updated_datetime": user.updated_datetime
    }

    return ProfileUpdateResponse(
        message="Profile updated successfully",
        updated_fields=updated_fields,
        user=user_profile
    )
