"""
Profile route: upload_profile_image.

Split out of the original monolithic profile.py (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5 follow-up).
"""

import os
from datetime import datetime

from fastapi import APIRouter, HTTPException, status, Request, UploadFile, File

from app.middleware.auth_middleware import get_current_user_required
from app.services.file_storage import get_file_storage_service

from app.schemas.user import ProfileImageUploadResponse

router = APIRouter()

# Allowed image extensions for profile avatar upload
PROFILE_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
# Max size for profile image (5MB)
MAX_PROFILE_IMAGE_SIZE_BYTES = 5 * 1024 * 1024


@router.post("/profile/upload-image", response_model=ProfileImageUploadResponse)
async def upload_profile_image(
    file: UploadFile = File(..., description="Profile image file (jpg, png, gif, webp)"),
    request: Request = None,
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
