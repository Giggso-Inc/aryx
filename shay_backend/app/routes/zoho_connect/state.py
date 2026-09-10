"""Shared constants, domain mapping, and payload encoding for the
zoho_connect route package.

Split from the original app/routes/zoho_connect.py (Raven style-compliance
pass, see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).
"""

import base64
import json
import re

_SID_RE = re.compile(r'^[A-Za-z0-9_\-]{1,128}$')

_ZOHO_AUTH_URL = "https://accounts.zoho.com/oauth/v2/auth"

_ZOHO_CRM_SCOPES = "ZohoCRM.modules.ALL,ZohoCRM.settings.ALL,ZohoCRM.users.ALL"

# Keep in sync with mcp/tools/zoho_oauth.py — same dict, separate services.
_ZOHO_API_DOMAINS: dict[str, str] = {
    "accounts.zoho.com":     "www.zohoapis.com",
    "accounts.zoho.eu":      "www.zohoapis.eu",
    "accounts.zoho.in":      "www.zohoapis.in",
    "accounts.zoho.com.au":  "www.zohoapis.com.au",
    "accounts.zoho.uk":      "www.zohoapis.uk",
    "accounts.zoho.jp":      "www.zohoapis.jp",
    "accounts.zoho.sa":      "www.zohoapis.sa",
    "accounts.zohocloud.ca": "www.zohoapis.ca",
}


def _api_base(accounts_server: str) -> str:
    host = accounts_server.strip("/").replace("https://", "").replace("http://", "")
    return "https://" + _ZOHO_API_DOMAINS.get(
        host, host.replace("accounts.zoho", "www.zohoapis")
    )


def _encode_payload(data: dict) -> str:
    """Encode a dict as base64url JSON (no padding) — same pattern as gmail_connect."""
    return base64.urlsafe_b64encode(
        json.dumps(data, separators=(",", ":")).encode()
    ).decode().rstrip("=")
