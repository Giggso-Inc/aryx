"""
Authentication middleware for JWT token validation.

Package split from the former single-file
app/middleware/auth_middleware.py — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md:
- asgi.py        — AuthMiddleware (raw ASGI middleware)
- current_user.py — get_current_user / get_current_user_required /
                     get_current_user_optional / _user_has_used_invitation
- decorators.py   — require_auth / optional_auth

Re-exports every name external code imported from
`app.middleware.auth_middleware` before the split (grepped: 137 files import
AuthMiddleware and/or get_current_user_required; nothing else was imported
externally, but every other name is re-exported too for completeness).
"""

from app.middleware.auth_middleware.asgi import AuthMiddleware
from app.middleware.auth_middleware.current_user import (
    _user_has_used_invitation,
    get_current_user,
    get_current_user_optional,
    get_current_user_required,
)
from app.middleware.auth_middleware.decorators import optional_auth, require_auth

__all__ = [
    "AuthMiddleware",
    "get_current_user",
    "get_current_user_required",
    "get_current_user_optional",
    "_user_has_used_invitation",
    "require_auth",
    "optional_auth",
]
