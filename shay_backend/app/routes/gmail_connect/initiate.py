"""
GET /connect/initiate — build the Google OAuth authorization URL for Gmail
scopes and return it for MCP to show to the user.

Split from the original app/routes/gmail_connect.py (Raven style-compliance
pass, see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).
"""

import secrets
from urllib.parse import urlencode

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.services.sso_service import build_state, is_allowed_redirect_uri

from .state import _GMAIL_SCOPES, _GOOGLE_AUTH_URL, _SID_RE

router = APIRouter()


@router.get("/connect/initiate")
async def gmail_connect_initiate(
    request: Request,
    sid: str = Query(..., description="MCP session ID"),
    redirect_uri: str = Query(..., description="MCP gmail callback URL to redirect back to"),
) -> JSONResponse:
    """
    Start the Gmail OAuth flow.
    Returns the Google authorization URL for the MCP to show to the user.
    """
    if not _SID_RE.match(sid):
        return JSONResponse({"error": "invalid_sid"}, status_code=400)
    if not is_allowed_redirect_uri(redirect_uri):
        return JSONResponse({"error": "invalid_redirect_uri"}, status_code=400)

    csrf_token = secrets.token_urlsafe(32)
    state = build_state(invite_id=sid, redirect_uri=redirect_uri, csrf_token=csrf_token)

    auth_url = (
        _GOOGLE_AUTH_URL + "?"
        + urlencode({
            "client_id":     settings.GOOGLE_CLIENT_ID,
            "redirect_uri":  settings.GOOGLE_GMAIL_REDIRECT_URI,
            "response_type": "code",
            "scope":         _GMAIL_SCOPES,
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
