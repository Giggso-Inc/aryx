"""
Reset-password (token-based) request/response schemas.

Split out of the former app/schemas/user/password.py during Phase 5b
file-size compliance work. See app/schemas/user/password/__init__.py for
the full sub-package layout and re-export list.
"""

from pydantic import BaseModel, Field, model_validator


class ResetPasswordRequest(BaseModel):
    """Reset password request schema - server validates the emailed reset token."""
    token: str = Field(..., min_length=1, description="Opaque password reset token from the email link")
    new_password: str = Field(..., min_length=8, description="New password (encrypted or plain text based on encrypted flag)")
    confirm_new_password: str = Field(..., min_length=8, description="Confirm new password (encrypted or plain text based on encrypted flag)")
    encrypted: bool = Field(default=False, description="Indicates if passwords are encrypted")

    # Password match validation is handled in the route handler after decryption
    # to avoid issues with encrypted password comparison

    @model_validator(mode='after')
    def validate_password_strength(self) -> "ResetPasswordRequest":
        """Validate password strength (skips validation for encrypted passwords)"""
        # Skip validation if password is encrypted
        if self.encrypted:
            return self

        # Only validate strength for plain text passwords
        if len(self.new_password) < 8:
            raise ValueError('Password must be at least 8 characters long')
        if not any(c.isupper() for c in self.new_password):
            raise ValueError('Password must contain at least one uppercase letter')
        if not any(c.islower() for c in self.new_password):
            raise ValueError('Password must contain at least one lowercase letter')
        if not any(c.isdigit() for c in self.new_password):
            raise ValueError('Password must contain at least one digit')
        if not any(c in '!@#$%^&*()_+-=[]{}|;:,.<>?' for c in self.new_password):
            raise ValueError('Password must contain at least one special character')
        return self

    class Config:
        json_schema_extra = {
            "example": {
                "token": "opaque-reset-token",
                "new_password": "MyNewSecurePassword123!",
                "confirm_new_password": "MyNewSecurePassword123!",
                "encrypted": False
            }
        }


class ResetPasswordResponse(BaseModel):
    """Reset password response schema"""
    message: str = Field(..., description="Success message")
    success: bool = Field(..., description="Whether password was reset successfully")

    class Config:
        json_schema_extra = {
            "example": {
                "message": "Password has been reset successfully",
                "success": True
            }
        }
