"""
User login request schemas.

Split out of the former app/schemas/user/auth_requests.py during Phase 5b
file-size compliance work. See app/schemas/user/auth_requests/__init__.py
for the full sub-package layout and re-export list.
"""

from pydantic import BaseModel, Field, EmailStr


class UserLoginRequest(BaseModel):
    """User login request schema"""
    email_id: EmailStr = Field(..., description="Email address")
    password: str = Field(..., description="User password")


class UserLoginEncryptedRequest(BaseModel):
    """User login request schema with encrypted password support"""
    email_id: EmailStr = Field(..., description="Email address")
    password: str = Field(..., description="Password (encrypted or plain text based on encrypted flag)")
    encrypted: bool = Field(default=False, description="Indicates if password is encrypted")
