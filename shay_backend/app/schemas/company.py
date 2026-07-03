"""
Company schemas for CRUD operations and management
"""

from datetime import datetime
from typing import Optional, List, Union, Dict, Any
from pydantic import BaseModel, EmailStr, Field, field_serializer, ConfigDict, AliasChoices
from uuid import UUID


class CompanyCreate(BaseModel):
    """Company creation request schema"""
    name: str = Field(..., min_length=1, max_length=255)
    domain: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    subscription_plan: str = "free"
    max_users: str = "10"
    max_workspaces: str = "5"
    max_storage_gb: str = "1"
    ai_enabled: bool = True
    ai_provider: str = "openai"


class CompanyCreateSimple(BaseModel):
    """Simplified company creation request schema"""
    name: str = Field(..., min_length=1, max_length=255, description="Company name")
    domain: Optional[str] = Field(None, max_length=255, description="Company domain")
    contactEmail: str = Field(..., description="Contact email for admin user")
    userName: Optional[str] = Field(None, max_length=255, description="Name of the first user for the company")
    industry: Optional[str] = Field(None, max_length=100, description="Company industry (stored in description)")
    status: str = Field(default="active", description="Company status")
    planId: Optional[str] = Field(None, description="Subscription plan ID")
    password: str = Field(..., min_length=6, description="Admin user password")


class CompanyCreateSimpleEncrypted(BaseModel):
    """Simplified company creation request schema with encrypted password support"""
    model_config = ConfigDict(populate_by_name=True)
    name: str = Field(..., min_length=1, max_length=255, description="Company name")
    domain: Optional[str] = Field(None, max_length=255, description="Company domain")
    contactEmail: str = Field(..., description="Contact email for admin user")
    userName: Optional[str] = Field(None, max_length=255, description="Name of the first user for the company")
    industry: Optional[str] = Field(None, max_length=100, description="Company industry (stored in description)")
    status: str = Field(default="active", description="Company status")
    planId: Optional[str] = Field(None, description="Subscription plan ID")
    password: str = Field(..., description="Password (encrypted or plain text based on encrypted flag)")
    encrypted: bool = Field(default=False, description="Indicates if password is encrypted")
    # Accept both snake_case and camelCase so Zaptag/verification flow works when client sends platformName/platformUrl
    platform_name: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("platform_name", "platformName"),
        description="Platform name for email templates (e.g., 'Prism 7', 'Zaptag')",
    )
    platform_url: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("platform_url", "platformUrl"),
        description="Platform URL for email templates",
    )


class CompanySignupRequest(BaseModel):
    """Company signup request schema combining company and user data"""
    company: CompanyCreate
    user: dict = Field(..., description="User registration data including email and password")


class CompanyUpdate(BaseModel):
    """Company update request schema"""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    subscription_plan: Optional[str] = None
    max_users: Optional[str] = None
    max_workspaces: Optional[str] = None
    max_storage_gb: Optional[str] = None
    ai_enabled: Optional[bool] = None
    ai_provider: Optional[str] = None
    settings: Optional[Dict[str, Any]] = None


class CompanyResponse(BaseModel):
    """Company response schema"""
    id: Union[str, UUID]
    name: str
    domain: Optional[str] = None
    description: Optional[str] = None
    is_active: bool
    subscription_plan: str
    max_users: str
    max_workspaces: str
    max_storage_gb: str
    ai_enabled: bool
    ai_provider: str
    ai_webhook_url: Optional[str] = None
    settings: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime
    
    @field_serializer('id')
    def serialize_uuid(self, value: Union[str, UUID]) -> str:
        return str(value)
    
    class Config:
        from_attributes = True


class CompanyProfileUpdate(BaseModel):
    """Request schema for updating company profile (e.g. profile page)."""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None


class CompanyList(BaseModel):
    """Company list response schema"""
    companies: List[CompanyResponse]
    total: int
    page: int
    size: int


class CompanyStats(BaseModel):
    """Company statistics schema"""
    total_users: int
    total_workspaces: int
    total_messages: int
    total_attachments: int
    storage_used_gb: float
    subscription_plan: str


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


class CompanyCreationResponse(BaseModel):
    """Company creation response schema matching Node.js API"""
    customerId: str = Field(..., description="Company ID")
    companyName: str = Field(..., description="Company name")
    token: str = Field(..., description="API token")
    tokenId: str = Field(..., description="Token ID")
    zohoCustomerId: Optional[str] = Field(None, description="Zoho customer ID")
    planId: Optional[str] = Field(None, description="Subscription plan ID")
    planName: Optional[str] = Field(None, description="Subscription plan name")
    isDefaultPlan: Optional[bool] = Field(None, description="Whether this is the default plan") 