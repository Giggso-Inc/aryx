"""
Forget-password request/response schemas.

Split out of the former app/schemas/user/password.py during Phase 5b
file-size compliance work. See app/schemas/user/password/__init__.py for
the full sub-package layout and re-export list.
"""

from typing import Optional

from pydantic import BaseModel, EmailStr, Field, validator


class ForgetPasswordRequest(BaseModel):
    """Forget password request schema"""
    email_id: EmailStr = Field(..., description="Email address to send temporary password to")
    base_url: str = Field(..., description="Base URL for the reset password link (e.g., https://dev-zaptag.shay-ai.com)")
    template_id: Optional[str] = Field(None, description="Template ID for password reset email (optional)")
    app_name: Optional[str] = Field(None, description="Application name to use as product name in email. If not provided, product name will be determined from base_url")

    @validator('template_id')
    def validate_template_id(cls, v) -> Optional[str]:
        if v and not v.startswith('TMPLT_'):
            raise ValueError("Template ID must start with 'TMPLT_'")
        return v

    @validator('app_name')
    def validate_app_name(cls, v) -> Optional[str]:
        if v is not None and v.strip() == "":
            return None  # Convert empty string to None
        return v

    class Config:
        json_schema_extra = {
            "examples": [
                {
                    "email_id": "user@example.com",
                    "base_url": "https://dev-zaptag.shay-ai.com",
                    "template_id": "TMPLT_PASSWORD_RESET_001",
                    "app_name": "Shay Suite"
                },
                {
                    "email_id": "user@example.com",
                    "base_url": "https://dev-zaptag.shay-ai.com",
                    "template_id": "TMPLT_PASSWORD_RESET_001",
                    "app_name": "Log Analyzer"
                },
                {
                    "email_id": "user@example.com",
                    "base_url": "https://dev-zaptag.shay-ai.com",
                    "template_id": "TMPLT_PASSWORD_RESET_001",
                    "app_name": "Prism 7"
                },
                {
                    "email_id": "user@example.com",
                    "base_url": "https://dev-zaptag.shay-ai.com",
                    "template_id": "TMPLT_PASSWORD_RESET_001",
                    "app_name": "Zaptag"
                },
                {
                    "email_id": "user@example.com",
                    "base_url": "https://dev-zaptag.shay-ai.com",
                    "template_id": "TMPLT_PASSWORD_RESET_001"
                }
            ]
        }


class ForgetPasswordResponse(BaseModel):
    """Forget password response schema (mirrors invite: returns short link like registration_link)."""
    message: str = Field(..., description="Success message")
    email_sent: bool = Field(..., description="Whether email was sent successfully")
    reset_link: Optional[str] = Field(None, description="Short reset link (same format as invite registration_link); for frontend parity with register flow.")

    class Config:
        json_schema_extra = {
            "example": {
                "message": "Password reset link sent to your email address",
                "email_sent": True,
                "reset_link": "https://example.com/api/v1/redirect/Abc12Xy"
            }
        }
