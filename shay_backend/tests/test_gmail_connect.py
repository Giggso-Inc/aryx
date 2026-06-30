"""
Unit tests for /api/v1/gmail/connect/* endpoints.

No DB required — these routes only call external services (Google OAuth).
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
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-google-client-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-google-client-secret")
os.environ.setdefault("GOOGLE_GMAIL_REDIRECT_URI", "http://localhost:8000/api/v1/gmail/connect/callback")
sys.modules.setdefault("socketio", MagicMock())
sys.modules.setdefault("python_socketio", MagicMock())

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routes.gmail_connect import router

_VALID_SID      = "test-session-abc123"
_VALID_REDIRECT = "http://localhost:9090/gmail/callback"
_STATE          = "test-state-string"
_STATE_DATA     = {"invite_id": _VALID_SID, "redirect_uri": _VALID_REDIRECT}


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/gmail")
    return app


def _make_token_resp(token_json: dict, status: int = 200) -> MagicMock:
    m = MagicMock()
    m.status_code = status
    m.json.return_value = token_json
    return m


def _make_profile_resp(profile_json: dict, status: int = 200) -> MagicMock:
    m = MagicMock()
    m.status_code = status
    m.json.return_value = profile_json
    return m


def _make_httpx_side_effect(*resps):
    """Return side_effect list for httpx.AsyncClient: each call yields next context manager."""
    mocks = []
    for (resp, method) in resps:
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=cm)
        cm.__aexit__ = AsyncMock(return_value=None)
        if method == "post":
            cm.post = AsyncMock(return_value=resp)
        else:
            cm.get = AsyncMock(return_value=resp)
        mocks.append(cm)
    return mocks


# ── initiate endpoint ─────────────────────────────────────────────────────────

def test_initiate_rejects_invalid_sid():
    """sid containing special chars or exceeding 128 chars must return 400."""
    client = TestClient(_make_app(), raise_server_exceptions=False)
    with patch("app.routes.gmail_connect.is_allowed_redirect_uri", return_value=True):
        resp = client.get(
            "/api/v1/gmail/connect/initiate",
            params={"sid": "bad sid with spaces!", "redirect_uri": _VALID_REDIRECT},
        )
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_sid"


def test_initiate_rejects_invalid_redirect_uri():
    """redirect_uri not in ALLOWED_ORIGINS must return 400."""
    client = TestClient(_make_app(), raise_server_exceptions=False)
    with patch("app.routes.gmail_connect.is_allowed_redirect_uri", return_value=False):
        resp = client.get(
            "/api/v1/gmail/connect/initiate",
            params={"sid": _VALID_SID, "redirect_uri": "https://evil.example.com/steal"},
        )
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_redirect_uri"


def test_initiate_happy_path_returns_authorization_url():
    """Valid sid and allowed redirect_uri must return a Google authorization_url."""
    client = TestClient(_make_app(), raise_server_exceptions=False)
    with patch("app.routes.gmail_connect.is_allowed_redirect_uri", return_value=True), \
         patch("app.routes.gmail_connect.build_state", return_value=_STATE):
        resp = client.get(
            "/api/v1/gmail/connect/initiate",
            params={"sid": _VALID_SID, "redirect_uri": _VALID_REDIRECT},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert "authorization_url" in body
    assert "accounts.google.com" in body["authorization_url"]
    assert "sso_csrf" in resp.cookies


# ── callback endpoint ─────────────────────────────────────────────────────────

def test_callback_state_failure_redirects_to_root():
    """Tampered or missing state must redirect to '/' (silent failure)."""
    client = TestClient(_make_app(), raise_server_exceptions=False)
    with patch("app.routes.gmail_connect.verify_state", side_effect=ValueError("bad state")):
        resp = client.get(
            "/api/v1/gmail/connect/callback",
            params={"code": "auth-code", "state": "tampered"},
            follow_redirects=False,
        )
    assert resp.status_code == 302
    assert resp.headers["location"] == "/"


def test_callback_provider_error_redirects_with_error_fragment():
    """When Google returns ?error=access_denied, callback must redirect with #error=access_denied."""
    client = TestClient(_make_app(), raise_server_exceptions=False)
    with patch("app.routes.gmail_connect.verify_state", return_value=_STATE_DATA):
        resp = client.get(
            "/api/v1/gmail/connect/callback",
            params={"error": "access_denied", "state": _STATE},
            follow_redirects=False,
        )
    assert resp.status_code == 302
    loc = resp.headers["location"]
    assert loc.startswith(_VALID_REDIRECT)
    assert "error=access_denied" in loc


def test_callback_token_exchange_failure_redirects_with_error():
    """httpx failure during code exchange must redirect with #error=token_exchange_failed."""
    client = TestClient(_make_app(), raise_server_exceptions=False)
    bad_cm = AsyncMock()
    bad_cm.__aenter__ = AsyncMock(return_value=bad_cm)
    bad_cm.__aexit__ = AsyncMock(return_value=None)
    bad_cm.post = AsyncMock(side_effect=Exception("network error"))

    with patch("app.routes.gmail_connect.verify_state", return_value=_STATE_DATA), \
         patch("app.routes.gmail_connect.httpx.AsyncClient", return_value=bad_cm):
        resp = client.get(
            "/api/v1/gmail/connect/callback",
            params={"code": "auth-code", "state": _STATE},
            follow_redirects=False,
        )
    assert resp.status_code == 302
    assert "error=token_exchange_failed" in resp.headers["location"]


def test_callback_no_email_redirects_with_error():
    """Google profile response with no email must redirect with #error=no_email."""
    client = TestClient(_make_app(), raise_server_exceptions=False)
    token_resp   = _make_token_resp({"access_token": "tok", "refresh_token": "ref"})
    profile_resp = _make_profile_resp({"sub": "user-123"})  # no email field

    mocks = _make_httpx_side_effect((token_resp, "post"), (profile_resp, "get"))
    with patch("app.routes.gmail_connect.verify_state", return_value=_STATE_DATA), \
         patch("app.routes.gmail_connect.httpx.AsyncClient", side_effect=mocks):
        resp = client.get(
            "/api/v1/gmail/connect/callback",
            params={"code": "auth-code", "state": _STATE},
            follow_redirects=False,
        )
    assert resp.status_code == 302
    assert "error=no_email" in resp.headers["location"]


def test_callback_happy_path_redirects_with_gmail_data_fragment():
    """Full happy path must redirect to mcp_redirect_uri with #gmail_data=<base64url>."""
    client = TestClient(_make_app(), raise_server_exceptions=False)
    token_resp   = _make_token_resp({
        "access_token": "google.access.token", "refresh_token": "google.refresh.token",
        "expires_in": 3600, "scope": "...", "token_type": "Bearer",
    })
    profile_resp = _make_profile_resp({"email": "user@gmail.com", "sub": "user-123"})

    mocks = _make_httpx_side_effect((token_resp, "post"), (profile_resp, "get"))
    with patch("app.routes.gmail_connect.verify_state", return_value=_STATE_DATA), \
         patch("app.routes.gmail_connect.httpx.AsyncClient", side_effect=mocks):
        resp = client.get(
            "/api/v1/gmail/connect/callback",
            params={"code": "auth-code", "state": _STATE},
            follow_redirects=False,
        )
    assert resp.status_code == 302
    loc = resp.headers["location"]
    assert loc.startswith(_VALID_REDIRECT + "#gmail_data=")

    fragment   = loc.split("#gmail_data=", 1)[1]
    padded     = fragment + "=" * ((4 - len(fragment) % 4) % 4)
    payload    = json.loads(base64.urlsafe_b64decode(padded))
    assert payload["access_token"] == "google.access.token"
    assert payload["email"] == "user@gmail.com"
    assert payload["_sid"] == _VALID_SID
