"""
GET /connect/callback — Google redirects here after the user grants Gmail
permissions. Exchanges the code for tokens, fetches the user email, and
redirects back to the MCP gmail callback with tokens in the URL fragment.

Split from the original app/routes/gmail_connect.py (Raven style-compliance
pass, see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).
"""

from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Query, Request
from fastapi.responses import RedirectResponse

from app.core.config import settings
from app.services.sso_service import verify_state

from .state import _GOOGLE_TOKEN_URL, _GOOGLE_USERINFO_URL, _encode_payload

router = APIRouter()


@router.get("/connect/callback")
async def gmail_connect_callback(
    request: Request,
    code: str = Query(default=None),
    state: str = Query(default=None),
    error: str = Query(default=None),
) -> RedirectResponse:
    """
    Google redirects here after the user grants Gmail permissions.
    Exchanges the code for tokens, fetches the user email, and redirects
    back to the MCP gmail callback with tokens encoded in the URL fragment.
    """
    cookie_csrf = request.cookies.get("sso_csrf")

    # Verify state before anything else — extracts sid and mcp_redirect_uri.
    try:
        state_data = verify_state(state, cookie_csrf)
    except Exception:
        return RedirectResponse(url="/", status_code=302)

    mcp_redirect_uri = state_data.get("redirect_uri", "")
    sid = state_data.get("invite_id", "")

    def _error_redirect(msg: str) -> RedirectResponse:
        fragment = urlencode({"error": msg, "_sid": sid})
        r = RedirectResponse(url=f"{mcp_redirect_uri}#{fragment}", status_code=302)
        r.delete_cookie("sso_csrf")
        return r

    if error:
        return _error_redirect(error)
    if not code:
        return _error_redirect("no_code")

    # Exchange authorization code for Google tokens.
    async with httpx.AsyncClient(timeout=30) as http:
        try:
            token_resp = await http.post(
                _GOOGLE_TOKEN_URL,
                data={
                    "code":          code,
                    "client_id":     settings.GOOGLE_CLIENT_ID,
                    "client_secret": settings.GOOGLE_CLIENT_SECRET,
                    "redirect_uri":  settings.GOOGLE_GMAIL_REDIRECT_URI,
                    "grant_type":    "authorization_code",
                },
            )
            token_data = token_resp.json()
        except Exception:
            return _error_redirect("token_exchange_failed")

    if token_resp.status_code != 200 or token_data.get("error"):
        return _error_redirect(token_data.get("error", "token_exchange_failed"))

    access_token = token_data.get("access_token")
    if not access_token:
        return _error_redirect("no_access_token")

    # Fetch user email via userinfo endpoint.
    async with httpx.AsyncClient(timeout=30) as http:
        try:
            info_resp = await http.get(
                _GOOGLE_USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            user_info = info_resp.json()
        except Exception:
            return _error_redirect("userinfo_failed")

    email = user_info.get("email", "")
    if not email:
        return _error_redirect("no_email")

    # Encode Google tokens + email as base64url JSON and redirect to MCP callback.
    payload = {
        "access_token":  access_token,
        "refresh_token": token_data.get("refresh_token", ""),
        "expires_in":    token_data.get("expires_in", 3600),
        "scope":         token_data.get("scope", ""),
        "token_type":    token_data.get("token_type", "Bearer"),
        "email":         email,
        "_sid":          sid,
    }
    gmail_data = _encode_payload(payload)

    response = RedirectResponse(
        url=f"{mcp_redirect_uri}#gmail_data={gmail_data}",
        status_code=302,
    )
    response.delete_cookie("sso_csrf")
    return response
