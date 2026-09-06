"""
GET /connect/initiate — generate a PKCE pair, embed the code_verifier in a
signed state, build the Salesforce auth URL, and return it.

Split from the original app/routes/sf_connect.py (Raven style-compliance
pass, see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).
"""

import secrets
from urllib.parse import urlencode

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.services.sso_service import is_allowed_redirect_uri

from .signing import _build_sf_state
from .state import _SF_AUTH_URL, _SID_RE, _pkce_pair

router = APIRouter()


@router.get("/connect/initiate")
async def sf_connect_initiate(
    request: Request,
    sid: str = Query(..., description="MCP session ID"),
    redirect_uri: str = Query(..., description="MCP salesforce callback URL to redirect back to"),
) -> JSONResponse:
    """
    Start the Salesforce OAuth flow.
    Returns the Salesforce authorization URL for the MCP to show to the user.
    """
    if not _SID_RE.match(sid):
        return JSONResponse({"error": "invalid_sid"}, status_code=400)
    if not is_allowed_redirect_uri(redirect_uri):
        return JSONResponse({"error": "invalid_redirect_uri"}, status_code=400)

    csrf_token = secrets.token_urlsafe(32)
    code_verifier, code_challenge = _pkce_pair()

    state = _build_sf_state(
        sid=sid,
        redirect_uri=redirect_uri,
        csrf_token=csrf_token,
        code_verifier=code_verifier,
    )

    auth_url = (
        _SF_AUTH_URL + "?"
        + urlencode({
            "client_id":             settings.SF_CONNECT_CLIENT_ID,
            "redirect_uri":          settings.SF_CONNECT_REDIRECT_URI,
            "response_type":         "code",
            "scope":                 "api refresh_token openid",
            "state":                 state,
            "code_challenge":        code_challenge,
            "code_challenge_method": "S256",
        })
    )

    response = JSONResponse({"authorization_url": auth_url})
    response.set_cookie(
        "sso_csrf", csrf_token,
        max_age=600, httponly=True, samesite="lax",
    )
    return response
