"""
SSO (Google / Microsoft) authentication service.

--------------------------------------------------------------------------
Package split (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md): this used to be a single
413-line app/services/sso_service.py (module-level functions, not a class).
It is now a package split by responsibility, with every name that any route
module imported re-exported here so `from app.services.sso_service import
X` needs zero changes anywhere else in the app.

  errors.py          - SSOError hierarchy (stable SSO_00x error codes)
  state.py           - HMAC-signed OAuth state build/verify + redirect-URI allow-list
  google.py          - Google OAuth authorization URL + code exchange / ID-token verify
  microsoft.py       - Microsoft OAuth authorization URL + code exchange / Graph lookup
  user_resolution.py - resolve_sso_user + default-workspace bootstrap
  tokens.py          - issue_tokens_for_user (access/refresh token issuance)
"""

from .errors import (
    SSOError,
    InvitationNotFoundError,
    InvitationInvalidError,
    SignupInviteRequiredError,
    EmailMismatchError,
    ProviderError,
)
from .state import (
    build_state,
    verify_state,
    is_allowed_redirect_uri,
)
from .google import (
    GOOGLE_TOKEN_URL,
    GOOGLE_JWKS_URL,
    GOOGLE_AUTH_URL,
    get_google_authorization_url,
    exchange_google_code,
)
from .microsoft import (
    MICROSOFT_AUTH_BASE,
    MICROSOFT_TOKEN_BASE,
    MICROSOFT_GRAPH_ME,
    get_microsoft_authorization_url,
    exchange_microsoft_code,
)
from .user_resolution import resolve_sso_user
from .tokens import issue_tokens_for_user

__all__ = [
    "SSOError",
    "InvitationNotFoundError",
    "InvitationInvalidError",
    "SignupInviteRequiredError",
    "EmailMismatchError",
    "ProviderError",
    "build_state",
    "verify_state",
    "is_allowed_redirect_uri",
    "GOOGLE_TOKEN_URL",
    "GOOGLE_JWKS_URL",
    "GOOGLE_AUTH_URL",
    "get_google_authorization_url",
    "exchange_google_code",
    "MICROSOFT_AUTH_BASE",
    "MICROSOFT_TOKEN_BASE",
    "MICROSOFT_GRAPH_ME",
    "get_microsoft_authorization_url",
    "exchange_microsoft_code",
    "resolve_sso_user",
    "issue_tokens_for_user",
]
