"""
User invitation (single + bulk) request schemas.

Split out of the former app/schemas/user/auth_requests.py during Phase 5b
file-size compliance work. See app/schemas/user/auth_requests/__init__.py
for the full sub-package layout and re-export list.
"""

from typing import Optional, List

from pydantic import BaseModel, Field, EmailStr, validator

import uuid


class UserInviteRequest(BaseModel):
    """User invitation request schema"""
    email: EmailStr = Field(..., description="Email address to send invitation to")
    company_id: str = Field(..., description="Company ID for the user")
    role: str = Field(default="user", description="User role (admin, user, guest)")
    user_id: Optional[str] = Field(None, description="User ID of the person sending the invitation")
    template_id: Optional[str] = Field(None, description="Template ID for invitation emails")
    platform_name: Optional[str] = Field(None, description="Platform display name supplied by the frontend")

    @validator('company_id')
    def validate_company_id(cls, v) -> str:
        try:
            uuid.UUID(v)
            return v
        except ValueError:
            raise ValueError("Invalid company_id format")

    @validator('user_id')
    def validate_user_id(cls, v) -> Optional[str]:
        if v:
            try:
                uuid.UUID(v)
                return v
            except ValueError:
                raise ValueError("Invalid user_id format")
        return v

    @validator('template_id')
    def validate_template_id(cls, v) -> Optional[str]:
        if v and len(v.strip()) == 0:
            raise ValueError("Template ID cannot be empty or whitespace")
        return v

    @validator('platform_name')
    def validate_platform_name(cls, v) -> Optional[str]:
        if v is not None and len(v.strip()) == 0:
            raise ValueError("Platform name cannot be empty or whitespace")
        return v


class BulkUserInviteItem(BaseModel):
    """Individual user invitation item for bulk operations"""
    email: EmailStr = Field(..., description="Email address to send invitation to")
    company_id: str = Field(..., description="Company ID for the user")
    role: str = Field(default="user", description="User role (admin, user, guest)")

    @validator('company_id')
    def validate_company_id(cls, v) -> str:
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
    def validate_template_id(cls, v) -> Optional[str]:
        if v and len(v.strip()) == 0:
            raise ValueError("Template ID cannot be empty or whitespace")
        return v

    @validator('user_id')
    def validate_user_id(cls, v) -> Optional[str]:
        if v:
            try:
                uuid.UUID(v)
                return v
            except ValueError:
                raise ValueError("Invalid user_id format")
        return v

    @validator('platform_name')
    def validate_platform_name(cls, v) -> Optional[str]:
        if v is not None and len(v.strip()) == 0:
            raise ValueError("Platform name cannot be empty or whitespace")
        return v
