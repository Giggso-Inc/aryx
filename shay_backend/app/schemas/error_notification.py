"""
Error notification request/response schemas
"""

from typing import Optional
from pydantic import BaseModel, Field, EmailStr


class ErrorNotificationRequest(BaseModel):
    """Request schema for API failure notification"""
    api_endpoint: str = Field(..., description="The API endpoint that failed")
    error_message: str = Field(..., description="Error message")
    error_type: Optional[str] = Field(None, description="Type of error (e.g., HTTPException, ValueError)")
    user_id: Optional[str] = Field(None, description="User ID who encountered the error")
    company_id: Optional[str] = Field(None, description="Company ID")
    request_method: Optional[str] = Field(None, description="HTTP method (GET, POST, etc.)")
    request_body: Optional[str] = Field(None, description="Request body (if applicable)")
    stack_trace: Optional[str] = Field(None, description="Stack trace of the error")
    support_email: Optional[EmailStr] = Field(None, description="Support email address (optional, uses default if not provided)")
    platform_name: Optional[str] = Field(None, description="Platform name for email notifications (optional, defaults to config value)")


class ErrorNotificationResponse(BaseModel):
    """Response schema for error notification"""
    success: bool = Field(..., description="Success status")
    message: str = Field(..., description="Response message")
    email_sent: bool = Field(..., description="Whether email was sent successfully")
    support_email: str = Field(..., description="Email address where notification was sent")

