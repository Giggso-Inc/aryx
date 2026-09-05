"""
Simple password update request schema (single confirm step, encrypted flag).

Split out of the former app/schemas/user/password.py during Phase 5b
file-size compliance work. See app/schemas/user/password/__init__.py for
the full sub-package layout and re-export list.
"""

from pydantic import BaseModel, Field, model_validator


class SimplePasswordUpdateRequest(BaseModel):
    """Simple password update request schema with old password confirmation and new password confirmation"""
    confirm_old_password: str = Field(
        ...,
        min_length=8,
        max_length=512,
        description="Current password confirmation (encrypted or plain text based on encrypted flag)",
        example="myCurrentPassword123"
    )
    new_password: str = Field(
        ...,
        min_length=8,
        max_length=512,
        description="New password (encrypted or plain text based on encrypted flag)",
        example="myNewSecurePassword456"
    )
    confirm_new_password: str = Field(
        ...,
        min_length=8,
        max_length=512,
        description="Confirmation of new password (encrypted or plain text based on encrypted flag)",
        example="myNewSecurePassword456"
    )
    encrypted: bool = Field(default=False, description="Indicates if passwords are encrypted")

    @model_validator(mode='after')
    def validate_passwords(self) -> "SimplePasswordUpdateRequest":
        """When encrypted=False, validate new password strength; when encrypted=True skip strength checks (ciphertext). Always require new and confirm to match."""
        # Confirm new password must match new password (works for both plain and encrypted)
        if self.new_password != self.confirm_new_password:
            raise ValueError('New password and confirmation password must match')
        # Run strength validation only when passwords are sent in plain text (not encrypted)
        if not self.encrypted:
            v = self.new_password
            if len(v) < 8:
                raise ValueError('Password must be at least 8 characters long')
            if not any(c.isupper() for c in v):
                raise ValueError('Password must contain at least one uppercase letter')
            if not any(c.islower() for c in v):
                raise ValueError('Password must contain at least one lowercase letter')
            if not any(c.isdigit() for c in v):
                raise ValueError('Password must contain at least one digit')
            if not any(c in '!@#$%^&*()_+-=[]{}|;:,.<>?' for c in v):
                raise ValueError('Password must contain at least one special character')
        return self

    class Config:
        json_schema_extra = {
            "example": {
                "confirm_old_password": "myCurrentPassword123",
                "new_password": "myNewSecurePassword456",
                "confirm_new_password": "myNewSecurePassword456",
                "encrypted": False
            },
            "description": "Password update: confirm old password, enter new password, and confirm it"
        }
