"""
Company user-invitation schemas.

Split out of the former app/schemas/company.py to keep each file under
the Raven 150-line style limit.
"""

from datetime import datetime
from typing import Optional, List, Union
from pydantic import BaseModel, EmailStr, Field, field_serializer
from uuid import UUID


class UserInvitation(BaseModel):
    """User invitation request schema"""
    email: EmailStr
    role: str = "user"
    message: Optional[str] = None


class InvitedByUser(BaseModel):
    """Schema for user who sent the invitation (include avatar_url for Invitations tab)."""
    userId: Union[str, UUID] = Field(..., description="User ID of the person who sent the invitation")
    userEmail: Optional[str] = Field(None, description="Email of the user who sent the invitation")
    username: Optional[str] = Field(None, description="Name/username of the user who sent the invitation")
    avatar_url: Optional[str] = Field(None, description="Avatar URL of the user who sent the invitation")
    role: Optional[str] = Field(None, description="Role of the user who sent the invitation")

    @field_serializer('userId')
    def serialize_uuid(self, value: Union[str, UUID]) -> str:
        return str(value)

    class Config:
        from_attributes = True


class UserInvitationResponse(BaseModel):
    """User invitation response schema"""
    id: Union[str, UUID]
    email: str
    role: str
    company_id: Union[str, UUID]
    invited_by: InvitedByUser
    status: str  # pending, accepted, expired
    message: Optional[str] = None
    created_at: datetime
    expires_at: datetime

    @field_serializer('id', 'company_id')
    def serialize_uuid(self, value: Union[str, UUID]) -> str:
        return str(value)

    class Config:
        from_attributes = True


class InvitationAccept(BaseModel):
    """Invitation acceptance request schema"""
    invitation_id: str
    name: Optional[str] = None
    avatar_url: Optional[str] = None


class InvitationListResponse(BaseModel):
    """Invitation list response schema with pagination"""
    invitations: List[UserInvitationResponse]
    total: int
    page: int
    size: int
    total_pages: int
    has_next: bool
    has_previous: bool
