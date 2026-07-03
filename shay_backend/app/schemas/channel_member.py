"""
Pydantic schemas for channel member operations
"""

from typing import Optional, List, Union, Dict, Any
from pydantic import BaseModel, Field, field_serializer, validator, EmailStr, ConfigDict, AliasChoices
from uuid import UUID


class ChannelMemberUserData(BaseModel):
    """Individual user data for channel membership."""
    user_id: str = Field(..., description="User ID to grant access")
    role: str = Field(..., description="Membership role (User or Admin)")
    permissions: Optional[Dict[str, Any]] = Field(None, description="Optional permissions for the user")

    @validator('role')
    def validate_role(cls, v):
        # Convert to lowercase for comparison, but accept any case variation
        v_lower = v.lower()
        allowed_roles = ['user', 'admin']
        if v_lower not in allowed_roles:
            raise ValueError(f'Role must be one of: {allowed_roles} (case-insensitive)')
        # Return the original value to preserve user's input case
        return v


class SingleChannelMemberCreate(BaseModel):
    """Request schema to add a single user to a channel by email."""
    model_config = ConfigDict(populate_by_name=True)
    mail_id: EmailStr = Field(..., description="Email address of the user to add")
    role: str = Field(..., description="Membership role (User or Admin)")
    permissions: Optional[Dict[str, Any]] = Field(None, description="Optional permissions for the user")
    # Accept both platform_name and platformName so client can send either (Accsell/Zaptag flow uses this)
    platform_name: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("platform_name", "platformName"),
        description="Platform name for email notifications (optional, defaults to config value)",
    )

    @validator('role')
    def validate_role(cls, v):
        # Convert to lowercase for comparison, but accept any case variation
        v_lower = v.lower()
        allowed_roles = ['user', 'admin']
        if v_lower not in allowed_roles:
            raise ValueError(f'Role must be one of: {allowed_roles} (case-insensitive)')
        # Return the original value to preserve user's input case
        return v


class ChannelMemberCreate(BaseModel):
    """Request schema to grant access to one or more users for a channel."""
    users: List[ChannelMemberUserData] = Field(..., description="List of users to grant access to")
    channel_id: str = Field(..., description="Channel ID to grant access to")

    @validator('users')
    def validate_users(cls, v):
        if not v:
            raise ValueError('At least one user must be specified')
        return v


class ChannelMemberResponse(BaseModel):
    """Response schema for channel member operations."""
    id: str = Field(..., description="Channel member ID")
    channel_id: str = Field(..., description="Channel ID")
    user_id: str = Field(..., description="User ID")
    role: str = Field(..., description="Member role")
    is_active: bool = Field(..., description="Whether the membership is active")
    permissions: Optional[Dict[str, Any]] = Field(None, description="Member permissions")
    created_at: Optional[str] = Field(None, description="Creation timestamp")
    updated_at: Optional[str] = Field(None, description="Last update timestamp")

    @field_serializer('created_at', 'updated_at')
    def serialize_datetime(self, dt):
        if dt:
            return dt.isoformat() if hasattr(dt, 'isoformat') else str(dt)
        return None


class ChannelMemberUserResponse(BaseModel):
    """Response schema for channel member with user details."""
    user_id: str = Field(..., description="User ID")
    email_id: Optional[str] = Field(None, description="User's email address")
    name: Optional[str] = Field(None, description="User's display name")
    avatar_url: Optional[str] = Field(None, description="User's avatar URL from DB")
    user_role: Optional[str] = Field(None, description="User's company role")
    membership_role: str = Field(..., description="User's role in the channel")
    company_id: Optional[str] = Field(None, description="Company ID of the user")
    company_name: Optional[str] = Field(None, description="Company name of the user")


class ChannelMemberList(BaseModel):
    """Response schema for list of channel members."""
    items: List[ChannelMemberResponse]
    total: int
    message: Optional[str] = Field(None, description="Response message for bulk operations")
    errors: Optional[List[str]] = Field(None, description="List of errors that occurred during bulk operations")


class ChannelMemberUserList(BaseModel):
    items: List[ChannelMemberUserResponse]
    total: int


class ChannelMemberUpdate(BaseModel):
    """Request schema to update a channel member's role."""
    role: str = Field(..., description="New role for the member")
    permissions: Optional[Dict[str, Any]] = Field(None, description="Optional permissions update")

    @validator('role')
    def validate_role(cls, v):
        # Convert to lowercase for comparison, but accept any case variation
        v_lower = v.lower()
        allowed_roles = ['user', 'admin']
        if v_lower not in allowed_roles:
            raise ValueError(f'Role must be one of: {allowed_roles} (case-insensitive)')
        # Return the original value to preserve user's input case
        return v


class ChannelMemberUpdateResponse(BaseModel):
    """Response schema for member role update."""
    message: str = Field(..., description="Success message for the update operation")
    updated_member: ChannelMemberResponse = Field(..., description="The updated channel member information")


class ChannelAccessCheckResponse(BaseModel):
    """Response schema for checking user access to a channel."""
    has_access: bool = Field(..., description="Whether the user has access to the channel")
    reason: str = Field(..., description="Reason for access decision (admin, public, member, company_mismatch, not_member)")


