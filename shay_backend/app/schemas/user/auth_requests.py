"""
User authentication and invitation request schemas (login, register, invite).

Split out of the former app/schemas/user.py during Phase 5a file-size
compliance work. See app/schemas/user/__init__.py for the full package
layout and re-export list.
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


class UserRegisterRequest(BaseModel):
    """User registration request schema"""
    invite_id: Optional[str] = Field(None, description="Invitation ID from email link (optional)")
    email_id: EmailStr = Field(..., description="Email address")
    password: str = Field(..., min_length=8, description="User password")
    name: Optional[str] = Field(None, description="User's full name (optional)")
    company_id: Optional[str] = Field(None, description="Company ID (required if no invite_id provided)")
    role: Optional[str] = Field(default="user", description="User role (default: user)")

    @validator('invite_id')
    def validate_invite_id(cls, v) -> Optional[str]:
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
    def validate_encrypted_param(cls, v) -> str:
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


# NOTE: this redefines UserRegisterEncryptedRequest, shadowing the simpler
# class above. This duplicate-definition quirk existed in the original
# monolithic app/schemas/user.py (the first definition became dead/
# unreachable the moment this one was parsed) and is preserved here
# unchanged so the module's runtime behavior is byte-for-byte identical:
# only this second class is ever bound to the name `UserRegisterEncryptedRequest`.
class UserRegisterEncryptedRequest(BaseModel):  # noqa: F811
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
    def validate_invite_id(cls, v) -> Optional[str]:
        if v:
            try:
                uuid.UUID(v)
            except ValueError:
                raise ValueError("Invalid invite_id format")
        return v

    @validator('encrypted_param')
    def validate_encrypted_param(cls, v) -> Optional[str]:
        if v and len(v.strip()) < 10:
            raise ValueError("Invalid encrypted_param format")
        return v
