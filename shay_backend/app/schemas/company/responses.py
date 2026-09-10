"""
Company response/list/stats schemas.

Split out of the former app/schemas/company.py to keep each file under
the Raven 150-line style limit.
"""

from datetime import datetime
from typing import Optional, List, Union, Dict, Any
from pydantic import BaseModel, Field, field_serializer
from uuid import UUID


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
