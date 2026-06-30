from typing import Optional, Literal

from pydantic import BaseModel, validator, EmailStr


class SSOInitiateRequest(BaseModel):
    provider: Literal["google", "microsoft"]
    invite_id: str
    redirect_uri: str


class SSOInitiateResponse(BaseModel):
    authorization_url: str
    state: str


class SSOCallbackQuery(BaseModel):
    code: str
    state: str
    error: Optional[str] = None
    error_description: Optional[str] = None


class SetPasswordRequestBody(BaseModel):
    email_id: EmailStr


class SetPasswordRequestResponse(BaseModel):
    message: str


class SetPasswordConfirmRequest(BaseModel):
    token: str
    user_id: str
    new_password: str
    confirm_password: str
    encrypted: bool = False

    @validator("new_password")
    def password_strength(cls, v):
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v

    @validator("confirm_password")
    def passwords_match(cls, v, values):
        if "new_password" in values and v != values["new_password"]:
            raise ValueError("Passwords do not match")
        return v


class SetPasswordConfirmResponse(BaseModel):
    message: str
    success: bool
