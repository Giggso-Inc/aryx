"""
GET /connect/callback — Salesforce redirects here after the user grants
permissions. Exchanges the code (with PKCE verifier from state), fetches
the user profile, and redirects back to the MCP salesforce callback with
tokens in the URL fragment.

Split from the original app/routes/sf_connect.py (Raven style-compliance
pass, see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).
"""

from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Query, Request
from fastapi.responses import RedirectResponse

from app.core.config import settings

from .signing import _verify_sf_state
from .state import _SF_TOKEN_URL, _encode_payload

router = APIRouter()


@router.get("/connect/callback")
async def sf_connect_callback(
    request: Request,
    code: str = Query(default=None),
    state: str = Query(default=None),
    error: str = Query(default=None),
) -> RedirectResponse:
    """
    Salesforce redirects here after the user grants permissions.
    Exchanges the code (with PKCE verifier from state), fetches the user profile,
    and redirects back to the MCP salesforce callback with tokens in the URL fragment.
    """
    cookie_csrf = request.cookies.get("sso_csrf")

    try:
        state_data = _verify_sf_state(state, cookie_csrf)
    except Exception:
        return RedirectResponse(url="/", status_code=302)

    mcp_redirect_uri = state_data.get("redirect_uri", "")
    sid = state_data.get("invite_id", "")
    code_verifier = state_data.get("cv", "")

    def _error_redirect(msg: str) -> RedirectResponse:
        fragment = urlencode({"error": msg, "_sid": sid})
        r = RedirectResponse(url=f"{mcp_redirect_uri}#{fragment}", status_code=302)
        r.delete_cookie("sso_csrf")
        return r

    if error:
        return _error_redirect(error)
    if not code:
        return _error_redirect("no_code")
    if not code_verifier:
        return _error_redirect("missing_code_verifier")

    # Exchange authorization code for Salesforce tokens (PKCE).
    async with httpx.AsyncClient(timeout=30) as http:
        try:
            token_resp = await http.post(
                _SF_TOKEN_URL,
                data={
                    "code":          code,
                    "client_id":     settings.SF_CONNECT_CLIENT_ID,
                    "client_secret": settings.SF_CONNECT_CLIENT_SECRET,
                    "redirect_uri":  settings.SF_CONNECT_REDIRECT_URI,
                    "grant_type":    "authorization_code",
                    "code_verifier": code_verifier,
                },
            )
            token_data = token_resp.json()
        except Exception:
            return _error_redirect("token_exchange_failed")

    if token_resp.status_code != 200 or token_data.get("error"):
        return _error_redirect(token_data.get("error", "token_exchange_failed"))

    access_token = token_data.get("access_token")
    instance_url = token_data.get("instance_url", "").rstrip("/")
    if not access_token:
        return _error_redirect("no_access_token")
    if not instance_url:
        return _error_redirect("no_instance_url")

    # Fetch Salesforce user profile via userinfo endpoint.
    async with httpx.AsyncClient(timeout=30) as http:
        try:
            profile_resp = await http.get(
                f"{instance_url}/services/oauth2/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            profile = profile_resp.json()
        except Exception:
            return _error_redirect("profile_fetch_failed")

    user_email = profile.get("email", "")
    if not user_email:
        return _error_redirect("no_email")

    # Encode tokens + profile as base64url JSON and redirect to MCP callback.
    payload = {
        "access_token":  access_token,
        "refresh_token": token_data.get("refresh_token", ""),
        "instance_url":  instance_url,
        "token_type":    token_data.get("token_type", "Bearer"),
        "scope":         token_data.get("scope", ""),
        "user_email":    user_email,
        "user_id":       profile.get("user_id", ""),
        "user_name":     profile.get("username", ""),
        "_sid":          sid,
    }
    sf_data = _encode_payload(payload)

    response = RedirectResponse(
        url=f"{mcp_redirect_uri}#sf_data={sf_data}",
        status_code=302,
    )
    response.delete_cookie("sso_csrf")
    return response
