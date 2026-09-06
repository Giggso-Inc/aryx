"""
GET /connect/callback — Zoho redirects here after the user grants CRM
permissions. Exchanges the code for tokens, fetches the user profile, and
redirects back to the MCP zoho callback with tokens in the URL fragment.

Split from the original app/routes/zoho_connect.py (Raven style-compliance
pass, see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).
"""

from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Query, Request
from fastapi.responses import RedirectResponse

from app.core.config import settings
from app.services.sso_service import verify_state

from .state import _ZOHO_API_DOMAINS, _api_base, _encode_payload

router = APIRouter()


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
