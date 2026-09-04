"""
Password update / forget / reset request+response schemas.

Split out of the former app/schemas/user.py during Phase 5a file-size
compliance work. See app/schemas/user/__init__.py for the full package
layout and re-export list.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, EmailStr, validator, field_validator, model_validator


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


class SimplePasswordUpdateRequest(BaseModel):
    """Simple password update request schema with old password confirmation and new password confirmation"""
    confirm_old_password: str = Field(
        ...,
        min_length=8,
        max_length=512,
        description="Current password confirmation (encrypted or plain text based on encrypted flag)",
        example="myCurrentPassword123"
    )
    new_password: str = Field(
        ...,
        min_length=8,
        max_length=512,
        description="New password (encrypted or plain text based on encrypted flag)",
        example="myNewSecurePassword456"
    )
    confirm_new_password: str = Field(
        ...,
        min_length=8,
        max_length=512,
        description="Confirmation of new password (encrypted or plain text based on encrypted flag)",
        example="myNewSecurePassword456"
    )
    encrypted: bool = Field(default=False, description="Indicates if passwords are encrypted")

    @model_validator(mode='after')
    def validate_passwords(self) -> "SimplePasswordUpdateRequest":
        """When encrypted=False, validate new password strength; when encrypted=True skip strength checks (ciphertext). Always require new and confirm to match."""
        # Confirm new password must match new password (works for both plain and encrypted)
        if self.new_password != self.confirm_new_password:
            raise ValueError('New password and confirmation password must match')
        # Run strength validation only when passwords are sent in plain text (not encrypted)
        if not self.encrypted:
            v = self.new_password
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
        return self

    class Config:
        json_schema_extra = {
            "example": {
                "confirm_old_password": "myCurrentPassword123",
                "new_password": "myNewSecurePassword456",
                "confirm_new_password": "myNewSecurePassword456",
                "encrypted": False
            },
            "description": "Password update: confirm old password, enter new password, and confirm it"
        }


class ForgetPasswordRequest(BaseModel):
    """Forget password request schema"""
    email_id: EmailStr = Field(..., description="Email address to send temporary password to")
    base_url: str = Field(..., description="Base URL for the reset password link (e.g., https://dev-zaptag.shay-ai.com)")
    template_id: Optional[str] = Field(None, description="Template ID for password reset email (optional)")
    app_name: Optional[str] = Field(None, description="Application name to use as product name in email. If not provided, product name will be determined from base_url")

    @validator('template_id')
    def validate_template_id(cls, v) -> Optional[str]:
        if v and not v.startswith('TMPLT_'):
            raise ValueError("Template ID must start with 'TMPLT_'")
        return v

    @validator('app_name')
    def validate_app_name(cls, v) -> Optional[str]:
        if v is not None and v.strip() == "":
            return None  # Convert empty string to None
        return v

    class Config:
        json_schema_extra = {
            "examples": [
                {
                    "email_id": "user@example.com",
                    "base_url": "https://dev-zaptag.shay-ai.com",
                    "template_id": "TMPLT_PASSWORD_RESET_001",
                    "app_name": "Shay Suite"
                },
                {
                    "email_id": "user@example.com",
                    "base_url": "https://dev-zaptag.shay-ai.com",
                    "template_id": "TMPLT_PASSWORD_RESET_001",
                    "app_name": "Log Analyzer"
                },
                {
                    "email_id": "user@example.com",
                    "base_url": "https://dev-zaptag.shay-ai.com",
                    "template_id": "TMPLT_PASSWORD_RESET_001",
                    "app_name": "Prism 7"
                },
                {
                    "email_id": "user@example.com",
                    "base_url": "https://dev-zaptag.shay-ai.com",
                    "template_id": "TMPLT_PASSWORD_RESET_001",
                    "app_name": "Zaptag"
                },
                {
                    "email_id": "user@example.com",
                    "base_url": "https://dev-zaptag.shay-ai.com",
                    "template_id": "TMPLT_PASSWORD_RESET_001"
                }
            ]
        }


class ForgetPasswordResponse(BaseModel):
    """Forget password response schema (mirrors invite: returns short link like registration_link)."""
    message: str = Field(..., description="Success message")
    email_sent: bool = Field(..., description="Whether email was sent successfully")
    reset_link: Optional[str] = Field(None, description="Short reset link (same format as invite registration_link); for frontend parity with register flow.")

    class Config:
        json_schema_extra = {
            "example": {
                "message": "Password reset link sent to your email address",
                "email_sent": True,
                "reset_link": "https://example.com/api/v1/redirect/Abc12Xy"
            }
        }


class ResetPasswordRequest(BaseModel):
    """Reset password request schema - server validates the emailed reset token."""
    token: str = Field(..., min_length=1, description="Opaque password reset token from the email link")
    new_password: str = Field(..., min_length=8, description="New password (encrypted or plain text based on encrypted flag)")
    confirm_new_password: str = Field(..., min_length=8, description="Confirm new password (encrypted or plain text based on encrypted flag)")
    encrypted: bool = Field(default=False, description="Indicates if passwords are encrypted")

    # Password match validation is handled in the route handler after decryption
    # to avoid issues with encrypted password comparison

    @model_validator(mode='after')
    def validate_password_strength(self) -> "ResetPasswordRequest":
        """Validate password strength (skips validation for encrypted passwords)"""
        # Skip validation if password is encrypted
        if self.encrypted:
            return self

        # Only validate strength for plain text passwords
        if len(self.new_password) < 8:
            raise ValueError('Password must be at least 8 characters long')
        if not any(c.isupper() for c in self.new_password):
            raise ValueError('Password must contain at least one uppercase letter')
        if not any(c.islower() for c in self.new_password):
            raise ValueError('Password must contain at least one lowercase letter')
        if not any(c.isdigit() for c in self.new_password):
            raise ValueError('Password must contain at least one digit')
        if not any(c in '!@#$%^&*()_+-=[]{}|;:,.<>?' for c in self.new_password):
            raise ValueError('Password must contain at least one special character')
        return self

    class Config:
        json_schema_extra = {
            "example": {
                "token": "opaque-reset-token",
                "new_password": "MyNewSecurePassword123!",
                "confirm_new_password": "MyNewSecurePassword123!",
                "encrypted": False
            }
        }


class ResetPasswordResponse(BaseModel):
    """Reset password response schema"""
    message: str = Field(..., description="Success message")
    success: bool = Field(..., description="Whether password was reset successfully")

    class Config:
        json_schema_extra = {
            "example": {
                "message": "Password has been reset successfully",
                "success": True
            }
        }
