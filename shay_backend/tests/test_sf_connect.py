"""
Unit tests for /api/v1/sf/connect/* endpoints.

No DB required — these routes only call external services (Salesforce OAuth).
External httpx calls are mocked; _verify_sf_state/_build_sf_state are patched where needed.
"""
import base64
import json
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://accsell_user:accsell_pass@localhost:5433/accsell_test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-tests-only")
os.environ.setdefault("ML_API_KEY", base64.b64encode(b"test-ml-key").decode())
os.environ.setdefault("SF_CONNECT_CLIENT_ID", "test-sf-client-id")
os.environ.setdefault("SF_CONNECT_CLIENT_SECRET", "test-sf-client-secret")
os.environ.setdefault("SF_CONNECT_REDIRECT_URI", "http://localhost:8000/api/v1/sf/connect/callback")
sys.modules.setdefault("socketio", MagicMock())
sys.modules.setdefault("python_socketio", MagicMock())

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routes.sf_connect import router

_VALID_SID      = "test-session-sf123"
_VALID_REDIRECT = "http://localhost:9092/salesforce/callback"
_STATE_DATA     = {
    "invite_id": _VALID_SID,
    "redirect_uri": _VALID_REDIRECT,
    "csrf": "test-csrf-token",
    "cv": "test-code-verifier-value",
}
_INSTANCE_URL   = "https://myorg.my.salesforce.com"


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/sf")
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
    with patch("app.routes.sf_connect.is_allowed_redirect_uri", return_value=True):
        resp = client.get(
            "/api/v1/sf/connect/initiate",
            params={"sid": "bad sid with spaces!", "redirect_uri": _VALID_REDIRECT},
        )
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_sid"


def test_initiate_rejects_overlong_sid():
    """sid longer than 128 chars must return 400 invalid_sid."""
    client = TestClient(_make_app(), raise_server_exceptions=False)
    with patch("app.routes.sf_connect.is_allowed_redirect_uri", return_value=True):
        resp = client.get(
            "/api/v1/sf/connect/initiate",
            params={"sid": "a" * 200, "redirect_uri": _VALID_REDIRECT},
        )
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_sid"


def test_initiate_rejects_invalid_redirect_uri():
    """redirect_uri not in allowlist must return 400 invalid_redirect_uri."""
    client = TestClient(_make_app(), raise_server_exceptions=False)
    with patch("app.routes.sf_connect.is_allowed_redirect_uri", return_value=False):
        resp = client.get(
            "/api/v1/sf/connect/initiate",
            params={"sid": _VALID_SID, "redirect_uri": "https://evil.example.com/steal"},
        )
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_redirect_uri"


def test_initiate_happy_path_returns_sf_authorization_url():
    """Valid request must return a login.salesforce.com authorization_url with PKCE."""
    client = TestClient(_make_app(), raise_server_exceptions=False)
    with patch("app.routes.sf_connect.is_allowed_redirect_uri", return_value=True):
        resp = client.get(
            "/api/v1/sf/connect/initiate",
            params={"sid": _VALID_SID, "redirect_uri": _VALID_REDIRECT},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert "authorization_url" in body
    url = body["authorization_url"]
    assert "login.salesforce.com" in url
    assert "code_challenge=" in url
    assert "code_challenge_method=S256" in url
    assert "sso_csrf" in resp.cookies


# ── callback endpoint ─────────────────────────────────────────────────────────

def test_callback_state_failure_redirects_to_root():
    """Tampered state must redirect to '/'."""
    client = TestClient(_make_app(), raise_server_exceptions=False)
    with patch("app.routes.sf_connect._verify_sf_state", side_effect=ValueError("bad")):
        resp = client.get(
            "/api/v1/sf/connect/callback",
            params={"code": "c", "state": "tampered"},
            follow_redirects=False,
        )
    assert resp.status_code == 302
    assert resp.headers["location"] == "/"


def test_callback_provider_error_redirects_with_error_fragment():
    """Salesforce returning error=access_denied must redirect with #error= fragment."""
    client = TestClient(_make_app(), raise_server_exceptions=False)
    with patch("app.routes.sf_connect._verify_sf_state", return_value=_STATE_DATA):
        resp = client.get(
            "/api/v1/sf/connect/callback",
            params={"error": "access_denied", "state": "s"},
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
    bad_cm.post = AsyncMock(side_effect=Exception("connection refused"))

    with patch("app.routes.sf_connect._verify_sf_state", return_value=_STATE_DATA), \
         patch("app.routes.sf_connect.httpx.AsyncClient", return_value=bad_cm):
        resp = client.get(
            "/api/v1/sf/connect/callback",
            params={"code": "c", "state": "s"},
            follow_redirects=False,
        )
    assert resp.status_code == 302
    assert "error=token_exchange_failed" in resp.headers["location"]


def test_callback_no_email_redirects_with_error():
    """Salesforce userinfo with no email must redirect with error=no_email."""
    client = TestClient(_make_app(), raise_server_exceptions=False)
    token_cm   = _make_http_mock("post", {
        "access_token": "sf.tok", "instance_url": _INSTANCE_URL, "token_type": "Bearer"
    })
    profile_cm = _make_http_mock("get", {"user_id": "uid"})  # no email

    with patch("app.routes.sf_connect._verify_sf_state", return_value=_STATE_DATA), \
         patch("app.routes.sf_connect.httpx.AsyncClient", side_effect=[token_cm, profile_cm]):
        resp = client.get(
            "/api/v1/sf/connect/callback",
            params={"code": "c", "state": "s"},
            follow_redirects=False,
        )
    assert resp.status_code == 302
    assert "error=no_email" in resp.headers["location"]


def test_callback_happy_path_redirects_with_sf_data_fragment():
    """Full happy path must redirect to mcp_redirect with #sf_data=<base64url>."""
    client = TestClient(_make_app(), raise_server_exceptions=False)
    token_cm = _make_http_mock("post", {
        "access_token":  "sf.access.token",
        "refresh_token": "sf.refresh.token",
        "instance_url":  _INSTANCE_URL,
        "token_type":    "Bearer",
        "scope":         "api refresh_token openid",
    })
    profile_cm = _make_http_mock("get", {
        "email": "rep@salesforce.dev",
        "user_id": "sfuid",
        "username": "rep@salesforce.dev",
    })

    with patch("app.routes.sf_connect._verify_sf_state", return_value=_STATE_DATA), \
         patch("app.routes.sf_connect.httpx.AsyncClient", side_effect=[token_cm, profile_cm]):
        resp = client.get(
            "/api/v1/sf/connect/callback",
            params={"code": "c", "state": "s"},
            follow_redirects=False,
        )
    assert resp.status_code == 302
    loc = resp.headers["location"]
    assert loc.startswith(_VALID_REDIRECT + "#sf_data=")

    fragment = loc.split("#sf_data=", 1)[1]
    padded   = fragment + "=" * ((4 - len(fragment) % 4) % 4)
    payload  = json.loads(base64.urlsafe_b64decode(padded))
    assert payload["access_token"] == "sf.access.token"
    assert payload["instance_url"] == _INSTANCE_URL
    assert payload["user_email"] == "rep@salesforce.dev"
    assert payload["_sid"] == _VALID_SID


def test_callback_missing_instance_url_redirects_with_error():
    """Token response without instance_url must redirect with error=no_instance_url."""
    client = TestClient(_make_app(), raise_server_exceptions=False)
    token_cm = _make_http_mock("post", {"access_token": "tok"})  # no instance_url

    with patch("app.routes.sf_connect._verify_sf_state", return_value=_STATE_DATA), \
         patch("app.routes.sf_connect.httpx.AsyncClient", return_value=token_cm):
        resp = client.get(
            "/api/v1/sf/connect/callback",
            params={"code": "c", "state": "s"},
            follow_redirects=False,
        )
    assert resp.status_code == 302
    assert "error=no_instance_url" in resp.headers["location"]


# ── scope fix (removed api.All) ───────────────────────────────────────────────

def test_initiate_scope_does_not_contain_api_all():
    """
    Authorization URL must NOT include the invalid 'api.All' scope that was
    removed in this fix — Salesforce rejects it with invalid_scope.
    """
    client = TestClient(_make_app(), raise_server_exceptions=False)
    with patch("app.routes.sf_connect.is_allowed_redirect_uri", return_value=True):
        resp = client.get(
            "/api/v1/sf/connect/initiate",
            params={"sid": _VALID_SID, "redirect_uri": _VALID_REDIRECT},
        )
    assert resp.status_code == 200
    url = resp.json()["authorization_url"]
    assert "api.All" not in url


def test_initiate_scope_contains_only_valid_scopes():
    """Authorization URL scope must be exactly 'api refresh_token openid'."""
    client = TestClient(_make_app(), raise_server_exceptions=False)
    with patch("app.routes.sf_connect.is_allowed_redirect_uri", return_value=True):
        resp = client.get(
            "/api/v1/sf/connect/initiate",
            params={"sid": _VALID_SID, "redirect_uri": _VALID_REDIRECT},
        )
    assert resp.status_code == 200
    url = resp.json()["authorization_url"]
    # URL-encoded space → +; the scope value in the query string
    assert "scope=api+refresh_token+openid" in url or "scope=api%20refresh_token%20openid" in url


def test_pkce_pair_produces_valid_s256_challenge():
    """_pkce_pair must produce a verifier and a valid S256 code_challenge."""
    import hashlib
    from app.routes.sf_connect import _pkce_pair

    verifier, challenge = _pkce_pair()

    digest   = hashlib.sha256(verifier.encode()).digest()
    expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    assert challenge == expected
    assert len(verifier) > 40
