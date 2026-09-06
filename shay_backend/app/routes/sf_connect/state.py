"""Shared constants, PKCE helper, and payload encoding for the sf_connect
route package.

Split from the original app/routes/sf_connect.py (Raven style-compliance
pass, see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).
"""

import base64
import hashlib
import json
import re
import secrets

from app.core.config import settings

_SID_RE = re.compile(r'^[A-Za-z0-9_\-]{1,128}$')

_SF_AUTH_URL  = "https://login.salesforce.com/services/oauth2/authorize"
_SF_TOKEN_URL = "https://login.salesforce.com/services/oauth2/token"


def _pkce_pair() -> tuple[str, str]:
    """Generate a PKCE (code_verifier, code_challenge) pair using S256."""
    code_verifier  = secrets.token_urlsafe(96)
    digest         = hashlib.sha256(code_verifier.encode()).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return code_verifier, code_challenge


def _get_state_secret() -> str:
    return settings.SSO_STATE_SECRET


def _encode_payload(data: dict) -> str:
    """Encode a dict as base64url JSON (no padding) — same pattern as gmail/zoho connect."""
    return base64.urlsafe_b64encode(
        json.dumps(data, separators=(",", ":")).encode()
    ).decode().rstrip("=")
