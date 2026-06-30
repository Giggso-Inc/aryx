"""
Salesforce Connect OAuth proxy — lets MCP route Salesforce workspace connectivity
through shay_backend's registered Salesforce Connected App.

Uses PKCE (S256): the code_verifier is embedded inside the HMAC-signed state so
no server-side storage is needed for the verifier.

Flow:
  1. MCP calls GET /api/v1/sf/connect/initiate?sid=<session_id>&redirect_uri=<mcp_callback>
     → shay_backend generates PKCE pair, embeds code_verifier in signed state,
       builds Salesforce auth URL and returns it.
  2. User completes consent in browser.
  3. Salesforce redirects to shay_backend GET /api/v1/sf/connect/callback?code=&state=
     → shay_backend extracts code_verifier from state, exchanges the code,
       fetches the Salesforce user profile, encodes tokens as base64url JSON,
       and redirects to {mcp_redirect_uri}#sf_data=<base64>
  4. MCP's salesforce_callback.html reads the fragment, POSTs tokens to /salesforce/token.
"""
import base64
import hashlib
import hmac
import json
import re
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.core.config import settings
from app.services.sso_service import is_allowed_redirect_uri

router = APIRouter(tags=["Salesforce Connect"])

_SID_RE = re.compile(r'^[A-Za-z0-9_\-]{1,128}$')

_SF_AUTH_URL  = "https://login.salesforce.com/services/oauth2/authorize"
_SF_TOKEN_URL = "https://login.salesforce.com/services/oauth2/token"


def _pkce_pair() -> tuple[str, str]:
    """Generate a PKCE (code_verifier, code_challenge) pair using S256."""
    code_verifier  = secrets.token_urlsafe(96)
    digest         = hashlib.sha256(code_verifier.encode()).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return code_verifier, code_challenge


def _get_state_secret() -> str:
    return settings.SSO_STATE_SECRET or settings.SECRET_KEY


def _build_sf_state(
    sid: str,
    redirect_uri: str,
    csrf_token: str,
    code_verifier: str,
) -> str:
    """Build an HMAC-signed state that carries sid, redirect_uri, csrf, and code_verifier."""
    payload = {
        "invite_id":    sid,
        "redirect_uri": redirect_uri,
        "csrf":         csrf_token,
        "cv":           code_verifier,
    }
    payload_bytes = json.dumps(payload, sort_keys=True).encode()
    signature = hmac.new(
        _get_state_secret().encode(), payload_bytes, hashlib.sha256
    ).hexdigest()
    state_obj = {"p": payload, "s": signature}
    return base64.urlsafe_b64encode(json.dumps(state_obj).encode()).decode()


def _verify_sf_state(state: str, cookie_csrf: str | None) -> dict:
    """Verify and decode the Salesforce HMAC-signed state. Returns the payload dict."""
    try:
        state_obj = json.loads(base64.urlsafe_b64decode(state.encode()).decode())
        payload = state_obj["p"]
        received_sig = state_obj["s"]
        payload_bytes = json.dumps(payload, sort_keys=True).encode()
        expected_sig = hmac.new(
            _get_state_secret().encode(), payload_bytes, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected_sig, received_sig):
            raise ValueError("State signature mismatch")
        if cookie_csrf and not hmac.compare_digest(payload["csrf"], cookie_csrf):
            raise ValueError("CSRF token mismatch")
        return payload
    except Exception as e:
        raise ValueError(f"Invalid state: {e}")


def _encode_payload(data: dict) -> str:
    """Encode a dict as base64url JSON (no padding) — same pattern as gmail/zoho connect."""
    return base64.urlsafe_b64encode(
        json.dumps(data, separators=(",", ":")).encode()
    ).decode().rstrip("=")


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
