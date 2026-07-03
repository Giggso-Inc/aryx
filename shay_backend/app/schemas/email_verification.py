"""
Email verification request/response schemas
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, EmailStr


class EmailVerificationRequest(BaseModel):
    """Request schema for email verification"""
    token: str = Field(..., description="Verification token from email link")


class EmailVerificationResponse(BaseModel):
    """Response schema for email verification"""
    success: bool = Field(..., description="Success status")
    message: str = Field(..., description="Response message")
    access_token: Optional[str] = Field(None, description="JWT access token")
    refresh_token: Optional[str] = Field(None, description="JWT refresh token")
    token_type: str = Field(default="bearer", description="Token type")
    expires_in: int = Field(default=1800, description="Token expiration time in seconds")
    user_id: Optional[str] = Field(None, description="User ID")
    email_id: Optional[str] = Field(None, description="User email")
    name: Optional[str] = Field(None, description="User name")
    role: Optional[str] = Field(None, description="User role")
    company_id: Optional[str] = Field(None, description="Company ID")
    company_name: Optional[str] = Field(None, description="Company name")
    default_workspace_id: Optional[str] = Field(None, description="Default workspace ID")


class ResendVerificationRequest(BaseModel):
    """Request schema for resending verification email"""
    email: EmailStr = Field(..., description="Email address to resend verification to")
    platform_name: Optional[str] = Field(None, description="Platform name for email notifications (optional, defaults to config value)")


class ResendVerificationResponse(BaseModel):
    """Response schema for resending verification"""
    success: bool = Field(..., description="Success status")
    message: str = Field(..., description="Response message")
    email_sent: bool = Field(..., description="Whether email was sent successfully")


class VerificationStatusResponse(BaseModel):
    """Response schema for verification status check"""
    status: str = Field(..., description="Token status: valid, expired, used, invalid")
    is_valid: bool = Field(..., description="Whether token is valid")
    expires_at: Optional[datetime] = Field(None, description="Token expiration time")
    is_verified: bool = Field(default=False, description="Whether user is verified")
    is_pending: bool = Field(default=True, description="Whether verification is pending")

