"""Shared constants and payload encoding for the gmail_connect route package.

Split from the original app/routes/gmail_connect.py (Raven style-compliance
pass, see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).
"""

import base64
import json
import re

_SID_RE = re.compile(r'^[A-Za-z0-9_\-]{1,128}$')

_GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"

_GMAIL_SCOPES = " ".join([
    "openid",
    "email",
    "profile",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
])


def _encode_payload(data: dict) -> str:
    """Encode a dict as base64url JSON (no padding) — same pattern as SSO sso_data."""
    return base64.urlsafe_b64encode(
        json.dumps(data, separators=(",", ":")).encode()
    ).decode().rstrip("=")
