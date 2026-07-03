"""
Customer support request/response schemas.

Used for user-initiated support form submission and API responses.
"""

from datetime import datetime
from typing import Optional, List
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class SupportRequestCreate(BaseModel):
    """Request schema for submitting a support request (contact form)."""

    name: str = Field(..., min_length=1, max_length=255, description="User's name")
    email: EmailStr = Field(..., description="User's email for reply")
    description: str = Field(..., min_length=1, description="Description of the problem")
    subject: Optional[str] = Field(None, max_length=100, description="Optional category e.g. Login, Upload, General")
    company_id: Optional[UUID] = Field(None, description="Company ID so support can map the issue to the correct company")
    company_name: Optional[str] = Field(None, max_length=255, description="Company name for display in support ticket")
    user_id: Optional[UUID] = Field(None, description="User ID of the submitter (when authenticated)")


class SupportRequestUpdate(BaseModel):
    """Request schema for updating a support request (partial update)."""

    name: Optional[str] = Field(None, min_length=1, max_length=255, description="User's name")
    email: Optional[EmailStr] = Field(None, description="User's email for reply")
    description: Optional[str] = Field(None, min_length=1, description="Description of the problem")
    subject: Optional[str] = Field(None, max_length=100, description="Optional category e.g. Login, Upload, General")
    company_name: Optional[str] = Field(None, max_length=255, description="Company name for display in support ticket")


class SupportRequestResponse(BaseModel):
    """Response schema for support request submission."""

    success: bool = Field(..., description="Whether the request was stored and notified")
    message: str = Field(..., description="Response message")
    ticket_reference: str = Field(..., description="Unique ticket/reference number for tracking")
    created_at: Optional[datetime] = Field(None, description="When the request was created")

    class Config:
        from_attributes = True


class SupportRequestDetail(BaseModel):
    """Full support request detail for GET responses."""

    id: UUID = Field(..., description="Support request ID")
    company_id: Optional[UUID] = Field(None, description="Company ID")
    company_name: Optional[str] = Field(None, description="Company name")
    user_id: Optional[UUID] = Field(None, description="User ID of submitter")
    name: str = Field(..., description="User's name")
    email: str = Field(..., description="User's email")
    description: str = Field(..., description="Description of the problem")
    subject: Optional[str] = Field(None, description="Subject/category")
    ticket_reference: str = Field(..., description="Unique ticket reference")
    source: Optional[str] = Field(None, description="Source e.g. Support form")
    created_at: datetime = Field(..., description="When the request was created")

    class Config:
        from_attributes = True


class SupportRequestListResponse(BaseModel):
    """Paginated list of support requests for a company."""

    items: List[SupportRequestDetail] = Field(..., description="List of support requests")
    total: int = Field(..., description="Total count for the company")
    page: int = Field(..., ge=1, description="Current page")
    size: int = Field(..., ge=1, description="Page size")
    pages: int = Field(..., ge=0, description="Total pages")


class SupportRequestDeleteResponse(BaseModel):
    """Response schema for support request deletion."""

    message: str = Field(
        ...,
        description="Confirmation message when the support request is deleted (e.g. once the raised concern is resolved)",
    )
