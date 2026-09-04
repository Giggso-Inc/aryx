"""
User authentication response schemas (invite/login/register/list responses).

Split out of the former app/schemas/user.py during Phase 5a file-size
compliance work. See app/schemas/user/__init__.py for the full package
layout and re-export list.
"""

from datetime import datetime
from typing import Optional, Union, List

from pydantic import BaseModel, Field, field_serializer

import uuid


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


class BulkUserInviteResponse(BaseModel):
    """Bulk user invitation response schema"""
    message: str = Field(..., description="Success message")
    total_invited: int = Field(..., description="Total number of invitations sent")
    successful_invitations: List[UserInviteResponse] = Field(..., description="Successfully sent invitations")
    failed_invitations: List[dict] = Field(..., description="Failed invitations with reasons")


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
