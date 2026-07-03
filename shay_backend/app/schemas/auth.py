"""
Authentication schemas for request/response validation
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, Field


class Token(BaseModel):
    """Token response schema"""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user_id: str
    email: str
    role: str
    company_id: Optional[str] = None


class TokenData(BaseModel):
    """Token data schema"""
    user_id: str
    email: str
    role: str
    company_id: Optional[str] = None


class UserLogin(BaseModel):
    """User login request schema"""
    email: EmailStr
    password: Optional[str] = None  # For OAuth, password might be None


class UserCreate(BaseModel):
    """User creation request schema"""
    email: EmailStr
    name: Optional[str] = None
    role: str = "user"
    company_id: Optional[str] = None
    google_id: Optional[str] = None


from typing import Union
from uuid import UUID
from pydantic import field_serializer




class UserUpdate(BaseModel):
    """User update request schema"""
    name: Optional[str] = None
    avatar_url: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    preferences: Optional[str] = None


class OAuthLogin(BaseModel):
    """OAuth login request schema"""
    provider: str = "google"
    redirect_uri: Optional[str] = None


class OAuthCallback(BaseModel):
    """OAuth callback request schema"""
    code: str
    state: Optional[str] = None


class RefreshToken(BaseModel):
    """Refresh token request schema"""
    refresh_token: str


class LogoutRequest(BaseModel):
    """Logout request schema"""
    refresh_token: str 