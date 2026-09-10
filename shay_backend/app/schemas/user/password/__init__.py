"""
Password schemas sub-package (re-exports).

This sub-package replaces the former app/schemas/user/password.py, split
into update_request / simple_update / forget / reset modules to keep each
file under the Raven 150-line style limit. All public names are
re-exported here so existing `from app.schemas.user.password import X`
(and `from app.schemas.user import X`) imports keep working unchanged.
"""

from .update_request import PasswordUpdateRequest, PasswordUpdateResponse
from .simple_update import SimplePasswordUpdateRequest
from .forget import ForgetPasswordRequest, ForgetPasswordResponse
from .reset import ResetPasswordRequest, ResetPasswordResponse

__all__ = [
    "PasswordUpdateRequest",
    "PasswordUpdateResponse",
    "SimplePasswordUpdateRequest",
    "ForgetPasswordRequest",
    "ForgetPasswordResponse",
    "ResetPasswordRequest",
    "ResetPasswordResponse",
]
