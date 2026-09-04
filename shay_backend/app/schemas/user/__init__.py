"""
User-related Pydantic schemas for API request/response validation.

This package replaces the former single-file app/schemas/user.py (718
lines) as part of Raven Phase 5a file-size compliance. It is split into:

- auth_requests.py  -- invite/register/login request schemas
- auth_responses.py -- invite/login/register/list response schemas
- profile.py         -- profile update request/response schemas
- password.py        -- password update/forget/reset request+response schemas
- bulk_remove.py      -- bulk user removal request/response schemas

Every class below is re-exported here so `from app.schemas.user import X`
continues to work unchanged for every existing caller.

Author: Karthick Chandrasekar
Date: 2025-08-14
Version: 1.0.0
"""

from .auth_requests import (
    UserInviteRequest,
    BulkUserInviteItem,
    BulkUserInviteRequest,
    UserRegisterRequest,
    UserLoginRequest,
    UserLoginEncryptedRequest,
    UserRegisterEncryptedRequest,
)
from .auth_responses import (
    UserInviteResponse,
    RegistrationInviteResponse,
    BulkUserInviteResponse,
    UserResponse,
    WorkspaceResponse,
    UserTokenResponse,
    LoginResponse,
    UserListResponse,
    CurrentUserResponse,
)
from .profile import (
    UserUpdateRequest,
    CurrentUserUpdateRequest,
    ProfileUpdateRequest,
    ProfileUpdateResponse,
    ProfileImageUploadResponse,
    ProfilePhotoRemoveResponse,
)
from .password import (
    PasswordUpdateRequest,
    PasswordUpdateResponse,
    SimplePasswordUpdateRequest,
    ForgetPasswordRequest,
    ForgetPasswordResponse,
    ResetPasswordRequest,
    ResetPasswordResponse,
)
from .bulk_remove import (
    BulkRemoveUsersRequest,
    BulkRemoveUsersResponse,
)

__all__ = [
    "UserInviteRequest",
    "BulkUserInviteItem",
    "BulkUserInviteRequest",
    "UserRegisterRequest",
    "UserLoginRequest",
    "UserLoginEncryptedRequest",
    "UserRegisterEncryptedRequest",
    "UserInviteResponse",
    "RegistrationInviteResponse",
    "BulkUserInviteResponse",
    "UserResponse",
    "WorkspaceResponse",
    "UserTokenResponse",
    "LoginResponse",
    "UserListResponse",
    "CurrentUserResponse",
    "UserUpdateRequest",
    "CurrentUserUpdateRequest",
    "ProfileUpdateRequest",
    "ProfileUpdateResponse",
    "ProfileImageUploadResponse",
    "ProfilePhotoRemoveResponse",
    "PasswordUpdateRequest",
    "PasswordUpdateResponse",
    "SimplePasswordUpdateRequest",
    "ForgetPasswordRequest",
    "ForgetPasswordResponse",
    "ResetPasswordRequest",
    "ResetPasswordResponse",
    "BulkRemoveUsersRequest",
    "BulkRemoveUsersResponse",
]
