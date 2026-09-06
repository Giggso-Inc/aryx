"""
GET /connect/initiate — build the Zoho OAuth authorization URL with CRM
scopes and return it for MCP to show to the user.

Split from the original app/routes/zoho_connect.py (Raven style-compliance
pass, see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).
"""

import secrets
from urllib.parse import urlencode

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.services.sso_service import build_state, is_allowed_redirect_uri

from .state import _SID_RE, _ZOHO_AUTH_URL, _ZOHO_CRM_SCOPES

router = APIRouter()


@router.get("/connect/initiate")
async def zoho_connect_initiate(
    request: Request,
    sid: str = Query(..., description="MCP session ID"),
    redirect_uri: str = Query(..., description="MCP zoho callback URL to redirect back to"),
) -> JSONResponse:
    """
    Start the Zoho OAuth flow.
    Returns the Zoho authorization URL for the MCP to show to the user.
    """
    if not _SID_RE.match(sid):
        return JSONResponse({"error": "invalid_sid"}, status_code=400)
    if not is_allowed_redirect_uri(redirect_uri):
        return JSONResponse({"error": "invalid_redirect_uri"}, status_code=400)

    csrf_token = secrets.token_urlsafe(32)
    # invite_id slot carries the MCP session ID here (not a user invite UUID).
    state = build_state(invite_id=sid, redirect_uri=redirect_uri, csrf_token=csrf_token)

    auth_url = (
        _ZOHO_AUTH_URL + "?"
        + urlencode({
            "client_id":     settings.ZOHO_CRM_CONNECT_CLIENT_ID,
            "redirect_uri":  settings.ZOHO_CRM_CONNECT_REDIRECT_URI,
            "response_type": "code",
            "scope":         _ZOHO_CRM_SCOPES,
            "state":         state,
            "access_type":   "offline",
            "prompt":        "consent",
        })
    )

    response = JSONResponse({"authorization_url": auth_url})
    response.set_cookie(
        "sso_csrf", csrf_token,
        max_age=600, httponly=True, samesite="lax",
    )
    return response
