"""
Zoho CRM Connect OAuth proxy — lets MCP route Zoho workspace connectivity
through shay_backend's registered Zoho Connected App.

Flow:
  1. MCP calls GET /api/v1/zoho/connect/initiate?sid=<session_id>&redirect_uri=<mcp_callback>
     → shay_backend builds Zoho auth URL with CRM scopes and returns it.
  2. User completes consent in browser.
  3. Zoho redirects to shay_backend GET /api/v1/zoho/connect/callback?code=&state=&accounts-server=
     → shay_backend exchanges the code, fetches the Zoho user profile, encodes the
       tokens as base64url JSON, and redirects to:
       {mcp_redirect_uri}#zoho_data=<base64>
  4. MCP's zoho_callback.html reads the fragment, POSTs tokens to /zoho/token.
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

router = APIRouter(tags=["Zoho Connect"])

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


@router.get("/connect/callback")
async def zoho_connect_callback(
    request: Request,
    code: str = Query(default=None),
    state: str = Query(default=None),
    error: str = Query(default=None),
) -> RedirectResponse:
    """
    Zoho redirects here after the user grants CRM permissions.
    Exchanges the code for tokens, fetches the user profile, and redirects
    back to the MCP zoho callback with tokens encoded in the URL fragment.
    """
    # Zoho returns accounts-server as a query param with a hyphen — FastAPI
    # can't bind hyphenated names, so we read it from the raw query params.
    accounts_server = (
        request.query_params.get("accounts-server", "") or "https://accounts.zoho.com"
    ).rstrip("/")

    cookie_csrf = request.cookies.get("sso_csrf")

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

    # Validate accounts-server is a known Zoho domain — prevents SSRF on the token exchange.
    _host = accounts_server.replace("https://", "").replace("http://", "").strip("/")
    if _host not in _ZOHO_API_DOMAINS:
        return _error_redirect("invalid_accounts_server")

    # Exchange authorization code for Zoho tokens.
    token_url = accounts_server + "/oauth/v2/token"
    async with httpx.AsyncClient(timeout=30) as http:
        try:
            token_resp = await http.post(
                token_url,
                data={
                    "code":          code,
                    "client_id":     settings.ZOHO_CRM_CONNECT_CLIENT_ID,
                    "client_secret": settings.ZOHO_CRM_CONNECT_CLIENT_SECRET,
                    "redirect_uri":  settings.ZOHO_CRM_CONNECT_REDIRECT_URI,
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

    # Fetch Zoho user profile via the CRM users API.
    api_base = _api_base(accounts_server)
    async with httpx.AsyncClient(timeout=30) as http:
        try:
            profile_resp = await http.get(
                f"{api_base}/crm/v2/users?type=CurrentUser",
                headers={"Authorization": f"Zoho-oauthtoken {access_token}"},
            )
            profile_data = profile_resp.json()
        except Exception:
            return _error_redirect("profile_fetch_failed")

    user = (profile_data.get("users") or [{}])[0]
    user_email = user.get("email", "")
    if not user_email:
        return _error_redirect("no_email")

    # Encode tokens + profile as base64url JSON and redirect to MCP callback.
    payload = {
        "access_token":  access_token,
        "refresh_token": token_data.get("refresh_token", ""),
        "expires_in":    token_data.get("expires_in", 3600),
        "scope":         token_data.get("scope", ""),
        "token_type":    token_data.get("token_type", "Bearer"),
        "accounts_server": accounts_server,
        "user_email":    user_email,
        "user_id":       user.get("id", ""),
        "user_name":     user.get("full_name", ""),
        "_sid":          sid,
    }
    zoho_data = _encode_payload(payload)

    response = RedirectResponse(
        url=f"{mcp_redirect_uri}#zoho_data={zoho_data}",
        status_code=302,
    )
    response.delete_cookie("sso_csrf")
    return response
