"""
Gmail Connect OAuth proxy — lets MCP route Gmail workspace connectivity
through shay_backend's already-registered Google OAuth client.

Flow:
  1. MCP calls GET /api/v1/gmail/connect/initiate?sid=<session_id>&redirect_uri=<mcp_gmail_callback>
     → shay_backend builds Google auth URL with Gmail scopes and returns it.
  2. User completes consent in browser.
  3. Google redirects to shay_backend GET /api/v1/gmail/connect/callback?code=&state=
     → shay_backend exchanges the code, fetches the user email, encodes the
       Google tokens as base64url JSON, and redirects to:
       {mcp_redirect_uri}#gmail_data=<base64>
  4. MCP's gmail_callback.html reads the fragment, POSTs tokens to /gmail/token.
"""
import base64
import json
import re
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.core.config import settings
from app.services.sso_service import build_state, is_allowed_redirect_uri, verify_state

_SID_RE = re.compile(r'^[A-Za-z0-9_\-]{1,128}$')

router = APIRouter(tags=["Gmail Connect"])

_GOOGLE_AUTH_URL  = "https://accounts.google.com/o/oauth2/v2/auth"
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
