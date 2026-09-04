"""
User profile update/response schemas (name, avatar, preferences).

Split out of the former app/schemas/user.py during Phase 5a file-size
compliance work. See app/schemas/user/__init__.py for the full package
layout and re-export list.
"""

from typing import Optional, List


from pydantic import BaseModel, Field


class UserUpdateRequest(BaseModel):
    """User update request schema"""
    name: Optional[str] = Field(None, min_length=1, max_length=255, description="User's full name")
    role: Optional[str] = Field(None, description="User role")


class CurrentUserUpdateRequest(BaseModel):
    """Current user profile update request schema"""
    name: Optional[str] = Field(None, min_length=1, max_length=255, description="User's full name")
    avatar_url: Optional[str] = Field(None, max_length=500, description="User's avatar URL")
    preferences: Optional[dict] = Field(None, description="User preferences as JSON")


class ProfileUpdateRequest(BaseModel):
    """Profile update request schema for personal information updates"""
    name: Optional[str] = Field(
        None,
        min_length=1,
        max_length=255,
        description="User's full name",
        example="John Smith"
    )
    avatar_url: Optional[str] = Field(
        None,
        max_length=500,
        description="User's avatar URL",
        example="https://example.com/new-avatar.jpg"
    )
    preferences: Optional[dict] = Field(
        None,
        description="User preferences as JSON",
        example={
            "theme": "light",
            "language": "en",
            "notifications": True,
            "timezone": "UTC-8",
            "date_format": "MM/DD/YYYY"
        }
    )

    class Config:
        json_schema_extra = {
            "example": {
                "name": "John Smith",
                "avatar_url": "https://example.com/new-avatar.jpg",
                "preferences": {
                    "theme": "light",
                    "language": "en",
                    "notifications": True,
                    "timezone": "UTC-8",
                    "date_format": "MM/DD/YYYY"
                }
            }
        }


class ProfileUpdateResponse(BaseModel):
    """Profile update response schema"""
    message: str = Field(..., description="Success message")
    updated_fields: List[str] = Field(..., description="List of fields that were updated")
    user: dict = Field(..., description="Updated user profile information")

    class Config:
        json_schema_extra = {
            "example": {
                "message": "Profile updated successfully",
                "updated_fields": ["name", "avatar_url", "preferences"],
                "user": {
                    "id": "uuid-string",
                    "name": "John Smith",
                    "email_id": "john.doe@example.com",
                    "avatar_url": "https://example.com/new-avatar.jpg",
                    "role": "senior_developer",
                    "is_active": True,
                    "is_verified": True,
                    "oauth_provider": "local",
                    "preferences": {
                        "theme": "light",
                        "language": "en",
                        "notifications": True,
                        "timezone": "UTC-8",
                        "date_format": "MM/DD/YYYY"
                    },
                    "last_login": "2025-01-20T10:30:00Z",
                    "created_datetime": "2025-01-15T09:00:00Z",
                    "updated_datetime": "2025-01-20T11:45:00Z"
                }
            }
        }


class ProfileImageUploadResponse(BaseModel):
    """Response schema for profile image upload; returns URL to use in PUT /profile avatar_url."""
    avatar_url: str = Field(..., description="Public URL of the uploaded profile image")
    message: str = Field(default="Profile image uploaded successfully", description="Success message")


class ProfilePhotoRemoveResponse(BaseModel):
    """Response schema for profile photo remove/delete."""
    message: str = Field(..., description="Success message after removing profile photo")
