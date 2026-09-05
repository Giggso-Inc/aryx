"""
User registration request schemas.

Split out of the former app/schemas/user/auth_requests.py during Phase 5b
file-size compliance work. See app/schemas/user/auth_requests/__init__.py
for the full sub-package layout and re-export list.

NOTE: this module redefines UserRegisterEncryptedRequest, shadowing the
simpler class defined above it. This duplicate-definition quirk existed in
the original monolithic app/schemas/user.py (the first definition became
dead/unreachable the moment this one was parsed) and is preserved here
unchanged so behavior is byte-for-byte identical: only the second class is
ever bound to the name `UserRegisterEncryptedRequest`.
"""

from typing import Optional

from pydantic import BaseModel, Field, EmailStr, validator

import uuid


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


# See module docstring: this redefines UserRegisterEncryptedRequest above,
# shadowing it on purpose (preserved quirk from the original monolithic
# schema file).
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
