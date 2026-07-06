"""
User-related Pydantic schemas for API request/response validation.

This module contains all the Pydantic models used for user management operations,
including user creation, updates, responses, and list responses with pagination.
These schemas ensure data validation and proper serialization for the user API endpoints.

Author: Karthick Chandrasekar
Date: 2025-08-14
Version: 1.0.0
"""

# Standard library imports for date/time operations and type hints
from datetime import datetime
from typing import Optional, Union, List

# Pydantic imports for data validation, serialization, and field definitions
from pydantic import BaseModel, Field, EmailStr, field_serializer, validator, field_validator, model_validator

# Standard library import for UUID generation and validation
import uuid
from uuid import UUID


class UserInviteRequest(BaseModel):
    """User invitation request schema"""
    email: EmailStr = Field(..., description="Email address to send invitation to")
    company_id: str = Field(..., description="Company ID for the user")
    role: str = Field(default="user", description="User role (admin, user, guest)")
    user_id: Optional[str] = Field(None, description="User ID of the person sending the invitation")
    template_id: Optional[str] = Field(None, description="Template ID for invitation emails")
    platform_name: Optional[str] = Field(None, description="Platform display name supplied by the frontend")

    @validator('company_id')
    def validate_company_id(cls, v):
        try:
            uuid.UUID(v)
            return v
        except ValueError:
            raise ValueError("Invalid company_id format")
    
    @validator('user_id')
    def validate_user_id(cls, v):
        if v:
            try:
                uuid.UUID(v)
                return v
            except ValueError:
                raise ValueError("Invalid user_id format")
        return v

    @validator('template_id')
    def validate_template_id(cls, v):
        if v and len(v.strip()) == 0:
            raise ValueError("Template ID cannot be empty or whitespace")
        return v

    @validator('platform_name')
    def validate_platform_name(cls, v):
        if v is not None and len(v.strip()) == 0:
            raise ValueError("Platform name cannot be empty or whitespace")
        return v


class UserInviteResponse(BaseModel):
    """User invitation response schema"""
    message: str = Field(..., description="Success message")
    invite_id: str = Field(..., description="Invitation ID")
    email_id: str = Field(..., description="Email address invited")
    registration_link: str = Field(..., description="Registration link sent to user")
    expires_at: datetime = Field(..., description="Invitation expiration time")


class RegistrationInviteResponse(BaseModel):
    """Encrypted invitation payload decrypted for the registration form."""
    email_id: str = Field(..., description="Email address invited")
    invite_id: str = Field(..., description="Invitation ID")
    company_id: str = Field(..., description="Company ID")
    role: str = Field(..., description="User role")


class BulkUserInviteItem(BaseModel):
    """Individual user invitation item for bulk operations"""
    email: EmailStr = Field(..., description="Email address to send invitation to")
    company_id: str = Field(..., description="Company ID for the user")
    role: str = Field(default="user", description="User role (admin, user, guest)")
    
    @validator('company_id')
    def validate_company_id(cls, v):
        try:
            uuid.UUID(v)
            return v
        except ValueError:
            raise ValueError("Invalid company_id format")
    
    class Config:
        extra = "forbid"  # Reject any extra fields


class BulkUserInviteRequest(BaseModel):
    """Bulk user invitation request schema"""
    users: List[BulkUserInviteItem] = Field(..., min_items=1, max_items=100, description="List of users to invite")
    template_id: Optional[str] = Field(None, description="Template ID for invitation emails (applies to all users)")
    user_id: Optional[str] = Field(None, description="User ID of the person sending the invitations")
    platform_name: Optional[str] = Field(None, description="Platform display name supplied by the frontend")

    @validator('template_id')
    def validate_template_id(cls, v):
        if v and len(v.strip()) == 0:
            raise ValueError("Template ID cannot be empty or whitespace")
        return v
    
    @validator('user_id')
    def validate_user_id(cls, v):
        if v:
            try:
                uuid.UUID(v)
                return v
            except ValueError:
                raise ValueError("Invalid user_id format")
        return v

    @validator('platform_name')
    def validate_platform_name(cls, v):
        if v is not None and len(v.strip()) == 0:
            raise ValueError("Platform name cannot be empty or whitespace")
        return v


class BulkUserInviteResponse(BaseModel):
    """Bulk user invitation response schema"""
    message: str = Field(..., description="Success message")
    total_invited: int = Field(..., description="Total number of invitations sent")
    successful_invitations: List[UserInviteResponse] = Field(..., description="Successfully sent invitations")
    failed_invitations: List[dict] = Field(..., description="Failed invitations with reasons")


class UserRegisterRequest(BaseModel):
    """User registration request schema"""
    invite_id: Optional[str] = Field(None, description="Invitation ID from email link (optional)")
    email_id: EmailStr = Field(..., description="Email address")
    password: str = Field(..., min_length=8, description="User password")
    name: Optional[str] = Field(None, description="User's full name (optional)")
    company_id: Optional[str] = Field(None, description="Company ID (required if no invite_id provided)")
    role: Optional[str] = Field(default="user", description="User role (default: user)")

    @validator('invite_id')
    def validate_invite_id(cls, v):
        if v:
            try:
                uuid.UUID(v)
            except ValueError:
                raise ValueError("Invalid invite_id format")
        return v


class UserRegisterEncryptedRequest(BaseModel):
    """User registration request schema for encrypted invitations"""
    encrypted_param: str = Field(..., description="Encrypted parameter from invitation URL")
    password: str = Field(..., min_length=8, description="User password")
    name: Optional[str] = Field(None, description="User's full name")

    @validator('encrypted_param')
    def validate_encrypted_param(cls, v):
        if not v or len(v) < 10:
            raise ValueError("Invalid encrypted parameter")
        return v


class UserLoginRequest(BaseModel):
    """User login request schema"""
    email_id: EmailStr = Field(..., description="Email address")
    password: str = Field(..., description="User password")


class UserLoginEncryptedRequest(BaseModel):
    """User login request schema with encrypted password support"""
    email_id: EmailStr = Field(..., description="Email address")
    password: str = Field(..., description="Password (encrypted or plain text based on encrypted flag)")
    encrypted: bool = Field(default=False, description="Indicates if password is encrypted")


class UserRegisterEncryptedRequest(BaseModel):
    """User registration request schema with encrypted password support"""
    invite_id: Optional[str] = Field(None, description="Invitation ID from email link (optional)")
    encrypted_param: Optional[str] = Field(None, description="Encrypted invitation payload from email link (optional)")
    email_id: EmailStr = Field(..., description="Email address")
    password: str = Field(..., description="Password (encrypted or plain text based on encrypted flag)")
    name: Optional[str] = Field(None, description="User's full name (optional)")
    company_id: Optional[str] = Field(None, description="Company ID (required if no invite_id provided)")
    role: Optional[str] = Field(default="user", description="User role (default: user)")
    encrypted: bool = Field(default=False, description="Indicates if password is encrypted")

    @validator('invite_id')
    def validate_invite_id(cls, v):
        if v:
            try:
                uuid.UUID(v)
            except ValueError:
                raise ValueError("Invalid invite_id format")
        return v

    @validator('encrypted_param')
    def validate_encrypted_param(cls, v):
        if v and len(v.strip()) < 10:
            raise ValueError("Invalid encrypted_param format")
        return v


class UserResponse(BaseModel):
    """User response schema (include avatar_url for profile image in UI)."""
    user_id: Union[str, uuid.UUID] = Field(alias="id")
    name: str
    email_id: str
    avatar_url: Optional[str] = Field(None, description="User avatar URL from DB")
    company_id: Union[str, uuid.UUID]
    role: str
    is_active: bool
    last_login: Optional[datetime] = None
    created_datetime: datetime
    updated_datetime: datetime

    @field_serializer('user_id', 'company_id')
    def serialize_uuid(self, value: Union[str, uuid.UUID]) -> str:
        return str(value)

    class Config:
        from_attributes = True
        populate_by_name = True


class WorkspaceResponse(BaseModel):
    """Workspace response schema"""
    id: str = Field(..., description="Workspace ID")
    name: str = Field(..., description="Workspace name")
    description: Optional[str] = Field(None, description="Workspace description")
    company_id: str = Field(..., description="Company ID")
    created_by: Optional[str] = Field(None, description="User ID who created the workspace")
    is_active: bool = Field(..., description="Whether workspace is active")
    is_public: bool = Field(..., description="Whether workspace is public")
    ai_enabled: bool = Field(..., description="Whether AI is enabled")
    ai_provider: str = Field(..., description="AI provider")
    ai_model: str = Field(..., description="AI model")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")
    
    @field_serializer('id', 'company_id', 'created_by')
    def serialize_uuid(self, value: Union[str, uuid.UUID]) -> str:
        return str(value) if value else None
    
    class Config:
        from_attributes = True


class UserTokenResponse(BaseModel):
    """User token response schema"""
    access_token: str = Field(..., description="JWT access token")
    refresh_token: str = Field(..., description="JWT refresh token")
    token_type: str = Field(default="bearer", description="Token type")
    expires_in: int = Field(..., description="Token expiration time in seconds")
    user_id: str = Field(..., description="User ID")
    email_id: str = Field(..., description="User email")
    name: Optional[str] = Field(None, description="User name")
    avatar_url: Optional[str] = Field(None, description="User avatar URL from DB")
    role: str = Field(..., description="User role")
    company_id: str = Field(..., description="Company ID")
    company_name: Optional[str] = Field(None, description="Company name")
    default_workspace_id: Optional[str] = Field(None, description="Default workspace ID for the company")


class LoginResponse(BaseModel):
    """Login response schema matching Node.js API format"""
    token: str = Field(..., description="JWT access token")
    refreshToken: str = Field(..., description="JWT refresh token")
    user: dict = Field(..., description="User information")


class UserUpdateRequest(BaseModel):
    """User update request schema"""
    name: Optional[str] = Field(None, min_length=1, max_length=255, description="User's full name")
    role: Optional[str] = Field(None, description="User role")


class UserListResponse(BaseModel):
    """User list response schema with pagination"""
    users: List[UserResponse]
    total: int
    total_active: int
    total_inactive: int
    total_admin: int
    page: int
    size: int
    total_pages: int
    has_next: bool
    has_previous: bool


class CurrentUserResponse(BaseModel):
    """Current user profile response schema"""
    user_id: Union[str, uuid.UUID] = Field(alias="id")
    name: str
    email_id: str
    avatar_url: Optional[str] = None
    company_id: Union[str, uuid.UUID]
    role: str
    is_active: bool
    is_verified: bool
    oauth_provider: str
    preferences: Optional[dict] = None
    last_login: Optional[datetime] = None
    created_datetime: datetime
    updated_datetime: datetime
    
    @field_serializer('user_id', 'company_id')
    def serialize_uuid(self, value: Union[str, uuid.UUID]) -> str:
        return str(value)
    
    class Config:
        from_attributes = True
        populate_by_name = True


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
    def validate_new_password_strength(cls, v):
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
    def validate_first_confirm_password(cls, v, info):
        """Validate that first confirm password matches new password"""
        if 'new_password' in info.data and v != info.data['new_password']:
            raise ValueError('First confirmation password must match new password')
        return v
    
    @field_validator('confirm_new_password_again')
    @classmethod
    def validate_second_confirm_password(cls, v, info):
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
    def validate_passwords(self):
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
    def validate_template_id(cls, v):
        if v and not v.startswith('TMPLT_'):
            raise ValueError("Template ID must start with 'TMPLT_'")
        return v

    @validator('app_name')
    def validate_app_name(cls, v):
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
    def validate_password_strength(self):
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

class BulkRemoveUsersRequest(BaseModel):
    user_ids: list[UUID]

    @field_validator("user_ids")
    @classmethod
    def validate_user_ids(cls, v):
        if not v:
            raise ValueError("user_ids cannot be empty")
        if len(v) > 100:
            raise ValueError("Cannot remove more than 100 users at once")
        return list(set(v)) 


class BulkRemoveUsersResponse(BaseModel):
    message: str = Field(..., description="Success message")
    removed_user_ids: list[str] = Field(..., description="User IDs that were successfully removed")
    not_found_user_ids: list[str] = Field(default_factory=list, description="User IDs that were not found in the company")
    revoked_channel_memberships: int = Field(..., description="Number of revoked channel memberships")

    class Config:
        json_schema_extra = {
            "example": {
                "message": "3 user(s) removed from company successfully",
                "removed_user_ids": ["11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"],
                "not_found_user_ids": ["33333333-3333-3333-3333-333333333333"],
                "revoked_channel_memberships": 5
            }
        }
