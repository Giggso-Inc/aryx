"""
Unit tests for /api/v1/zoho/connect/* endpoints.

No DB required — these routes only call external services (Zoho OAuth).
External httpx calls are mocked; sso_service helpers are patched.
"""
import base64
import json
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://accsell_user:accsell_pass@localhost:5433/accsell_test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-tests-only")
os.environ.setdefault("ML_API_KEY", base64.b64encode(b"test-ml-key").decode())
os.environ.setdefault("ZOHO_CRM_CONNECT_CLIENT_ID", "test-zoho-client-id")
os.environ.setdefault("ZOHO_CRM_CONNECT_CLIENT_SECRET", "test-zoho-client-secret")
os.environ.setdefault("ZOHO_CRM_CONNECT_REDIRECT_URI", "http://localhost:8000/api/v1/zoho/connect/callback")
sys.modules.setdefault("socketio", MagicMock())
sys.modules.setdefault("python_socketio", MagicMock())

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routes.zoho_connect import router

_VALID_SID      = "test-session-zoho123"
_VALID_REDIRECT = "http://localhost:9091/zoho/callback"
_STATE          = "test-state-zoho"
_STATE_DATA     = {"invite_id": _VALID_SID, "redirect_uri": _VALID_REDIRECT}
_ACCOUNTS_SVR   = "https://accounts.zoho.com"


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/zoho")
    return app


def _make_http_mock(method: str, resp_json: dict, status: int = 200) -> AsyncMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = resp_json
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=cm)
    cm.__aexit__ = AsyncMock(return_value=None)
    setattr(cm, method, AsyncMock(return_value=resp))
    return cm


# ── initiate endpoint ─────────────────────────────────────────────────────────

def test_initiate_rejects_invalid_sid():
    """sid with special chars must return 400 invalid_sid."""
    client = TestClient(_make_app(), raise_server_exceptions=False)
    with patch("app.routes.zoho_connect.is_allowed_redirect_uri", return_value=True):
        resp = client.get(
            "/api/v1/zoho/connect/initiate",
            params={"sid": "bad sid with spaces!", "redirect_uri": _VALID_REDIRECT},
        )
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_sid"


def test_initiate_rejects_invalid_redirect_uri():
    """redirect_uri not in allowlist must return 400 invalid_redirect_uri."""
    client = TestClient(_make_app(), raise_server_exceptions=False)
    with patch("app.routes.zoho_connect.is_allowed_redirect_uri", return_value=False):
        resp = client.get(
            "/api/v1/zoho/connect/initiate",
            params={"sid": _VALID_SID, "redirect_uri": "https://evil.example.com/steal"},
        )
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_redirect_uri"


def test_initiate_happy_path_returns_authorization_url():
    """Valid request must return a Zoho accounts.zoho.com authorization_url."""
    client = TestClient(_make_app(), raise_server_exceptions=False)
    with patch("app.routes.zoho_connect.is_allowed_redirect_uri", return_value=True), \
         patch("app.routes.zoho_connect.build_state", return_value=_STATE):
        resp = client.get(
            "/api/v1/zoho/connect/initiate",
            params={"sid": _VALID_SID, "redirect_uri": _VALID_REDIRECT},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert "authorization_url" in body
    assert "accounts.zoho.com" in body["authorization_url"]
    assert "ZohoCRM" in body["authorization_url"]
    assert "sso_csrf" in resp.cookies


# ── callback endpoint ─────────────────────────────────────────────────────────

def test_callback_state_failure_redirects_to_root():
    """Tampered state must redirect to '/'."""
    client = TestClient(_make_app(), raise_server_exceptions=False)
    with patch("app.routes.zoho_connect.verify_state", side_effect=ValueError("bad")):
        resp = client.get(
            "/api/v1/zoho/connect/callback",
            params={"code": "c", "state": "tampered", "accounts-server": _ACCOUNTS_SVR},
            follow_redirects=False,
        )
    assert resp.status_code == 302
    assert resp.headers["location"] == "/"


def test_callback_provider_error_redirects_with_error_fragment():
    """Zoho returning error=access_denied must redirect with #error= fragment."""
    client = TestClient(_make_app(), raise_server_exceptions=False)
    with patch("app.routes.zoho_connect.verify_state", return_value=_STATE_DATA):
        resp = client.get(
            "/api/v1/zoho/connect/callback",
            params={"error": "access_denied", "state": _STATE},
            follow_redirects=False,
        )
    assert resp.status_code == 302
    assert "error=access_denied" in resp.headers["location"]


def test_callback_token_exchange_failure_redirects_with_error():
    """httpx failure during token exchange must redirect with error=token_exchange_failed."""
    client = TestClient(_make_app(), raise_server_exceptions=False)
    bad_cm = AsyncMock()
    bad_cm.__aenter__ = AsyncMock(return_value=bad_cm)
    bad_cm.__aexit__ = AsyncMock(return_value=None)
    bad_cm.post = AsyncMock(side_effect=Exception("timeout"))

    with patch("app.routes.zoho_connect.verify_state", return_value=_STATE_DATA), \
         patch("app.routes.zoho_connect.httpx.AsyncClient", return_value=bad_cm):
        resp = client.get(
            "/api/v1/zoho/connect/callback",
            params={"code": "c", "state": _STATE, "accounts-server": _ACCOUNTS_SVR},
            follow_redirects=False,
        )
    assert resp.status_code == 302
    assert "error=token_exchange_failed" in resp.headers["location"]


def test_callback_no_email_redirects_with_error():
    """Zoho profile with no email must redirect with error=no_email."""
    client = TestClient(_make_app(), raise_server_exceptions=False)
    token_cm   = _make_http_mock("post", {"access_token": "zoho.tok", "refresh_token": "ref"})
    profile_cm = _make_http_mock("get", {"users": [{"id": "uid", "full_name": "Rep"}]})  # no email

    with patch("app.routes.zoho_connect.verify_state", return_value=_STATE_DATA), \
         patch("app.routes.zoho_connect.httpx.AsyncClient", side_effect=[token_cm, profile_cm]):
        resp = client.get(
            "/api/v1/zoho/connect/callback",
            params={"code": "c", "state": _STATE, "accounts-server": _ACCOUNTS_SVR},
            follow_redirects=False,
        )
    assert resp.status_code == 302
    assert "error=no_email" in resp.headers["location"]


def test_callback_happy_path_redirects_with_zoho_data_fragment():
    """Full happy path must redirect to mcp_redirect with #zoho_data=<base64url>."""
    client = TestClient(_make_app(), raise_server_exceptions=False)
    token_cm = _make_http_mock("post", {
        "access_token": "zoho.access.token", "refresh_token": "zoho.refresh.token",
        "expires_in": 3600, "scope": "ZohoCRM.modules.ALL", "token_type": "Bearer",
    })
    profile_cm = _make_http_mock("get", {
        "users": [{"id": "uid123", "full_name": "Sales Rep", "email": "rep@zoho.dev"}]
    })

    with patch("app.routes.zoho_connect.verify_state", return_value=_STATE_DATA), \
         patch("app.routes.zoho_connect.httpx.AsyncClient", side_effect=[token_cm, profile_cm]):
        resp = client.get(
            "/api/v1/zoho/connect/callback",
            params={"code": "c", "state": _STATE, "accounts-server": _ACCOUNTS_SVR},
            follow_redirects=False,
        )
    assert resp.status_code == 302
    loc = resp.headers["location"]
    assert loc.startswith(_VALID_REDIRECT + "#zoho_data=")

    fragment = loc.split("#zoho_data=", 1)[1]
    padded   = fragment + "=" * ((4 - len(fragment) % 4) % 4)
    payload  = json.loads(base64.urlsafe_b64decode(padded))
    assert payload["access_token"] == "zoho.access.token"
    assert payload["user_email"] == "rep@zoho.dev"
    assert payload["accounts_server"] == _ACCOUNTS_SVR
    assert payload["_sid"] == _VALID_SID


def test_callback_invalid_accounts_server_redirects_with_error():
    """accounts-server not in the SSRF allowlist must redirect with error=invalid_accounts_server."""
    client = TestClient(_make_app(), raise_server_exceptions=False)
    with patch("app.routes.zoho_connect.verify_state", return_value=_STATE_DATA):
        resp = client.get(
            "/api/v1/zoho/connect/callback",
            params={"code": "c", "state": _STATE, "accounts-server": "https://evil.example.com"},
            follow_redirects=False,
        )
    assert resp.status_code == 302
    assert "error=invalid_accounts_server" in resp.headers["location"]


def test_callback_uses_accounts_server_from_query_param():
    """accounts-server query param (hyphenated) must set the token_url domain."""
    client = TestClient(_make_app(), raise_server_exceptions=False)
    eu_server  = "https://accounts.zoho.eu"
    token_cm   = _make_http_mock("post", {"access_token": "tok", "refresh_token": "ref"})
    profile_cm = _make_http_mock("get", {
        "users": [{"id": "u", "full_name": "EU Rep", "email": "eu@zoho.dev"}]
    })

    with patch("app.routes.zoho_connect.verify_state", return_value=_STATE_DATA), \
         patch("app.routes.zoho_connect.httpx.AsyncClient", side_effect=[token_cm, profile_cm]) as mock_cls:
        client.get(
            "/api/v1/zoho/connect/callback",
            params={"code": "c", "state": _STATE, "accounts-server": eu_server},
            follow_redirects=False,
        )
    # The first httpx call (token exchange) must POST to the EU accounts server
    first_post_url = str(token_cm.post.call_args[0][0])
    assert "zoho.eu" in first_post_url
