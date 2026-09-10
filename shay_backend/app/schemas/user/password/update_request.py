"""
Password update request/response schemas (three-step confirmation flow).

Split out of the former app/schemas/user/password.py during Phase 5b
file-size compliance work. See app/schemas/user/password/__init__.py for
the full sub-package layout and re-export list.
"""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class PasswordUpdateRequest(BaseModel):
    """Password update request schema"""
    new_password: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="New password (must be different from old password)",
        example="myNewSecurePassword456"
    )
    confirm_new_password: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="First confirmation of new password",
        example="myNewSecurePassword456"
    )
    confirm_new_password_again: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="Second confirmation of new password (must match first confirmation)",
        example="myNewSecurePassword456"
    )
    old_password: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="Current password (verified last)",
        example="myCurrentPassword123"
    )

    @field_validator('new_password')
    @classmethod
    def validate_new_password_strength(cls, v) -> str:
        """Validate new password strength"""
        if len(v) < 8:
            raise ValueError('Password must be at least 8 characters long')
        if not any(c.isupper() for c in v):
            raise ValueError('Password must contain at least one uppercase letter')
        if not any(c.islower() for c in v):
            raise ValueError('Password must contain at least one lowercase letter')
        if not any(c.isdigit() for c in v):
            raise ValueError('Password must contain at least one digit')
        if not any(c in '!@#$%^&*()_+-=[]{}|;:,.<>?' for c in v):
            raise ValueError('Password must contain at least one special character')
        return v

    @field_validator('confirm_new_password')
    @classmethod
    def validate_first_confirm_password(cls, v, info) -> str:
        """Validate that first confirm password matches new password"""
        if 'new_password' in info.data and v != info.data['new_password']:
            raise ValueError('First confirmation password must match new password')
        return v

    @field_validator('confirm_new_password_again')
    @classmethod
    def validate_second_confirm_password(cls, v, info) -> str:
        """Validate that second confirm password matches new password"""
        if 'new_password' in info.data and v != info.data['new_password']:
            raise ValueError('Second confirmation password must match new password')
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "new_password": "myNewSecurePassword456",
                "confirm_new_password": "myNewSecurePassword456",
                "confirm_new_password_again": "myNewSecurePassword456",
                "old_password": "myCurrentPassword123"
            },
            "description": "Password update flow: 1) Enter new password, 2) Confirm new password twice, 3) Verify current password"
        }


class PasswordUpdateResponse(BaseModel):
    """Password update response schema"""
    message: str = Field(..., description="Success message")
    updated_at: datetime = Field(..., description="Timestamp when password was updated")

    class Config:
        json_schema_extra = {
            "example": {
                "message": "Password updated successfully",
                "updated_at": "2025-01-20T12:00:00Z"
            }
        }
