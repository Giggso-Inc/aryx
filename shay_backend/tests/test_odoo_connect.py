"""
Unit tests for Odoo Connect — Bearer token forwarding changes.

Covers:
- verify-url returns 401 when no token in _sid_token_store (missing Bearer on initiate)
- verify-url forwards the stored Bearer token to the orchestrator
- complete returns session_token_missing redirect when token store is empty

No DB required — external httpx calls are mocked.
"""
import base64
import json
import os
import sys
import time
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://accsell_user:accsell_pass@localhost:5433/accsell_test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-tests-only")
os.environ.setdefault("ML_API_KEY", base64.b64encode(b"test-ml-key").decode())
sys.modules.setdefault("socketio", MagicMock())
sys.modules.setdefault("python_socketio", MagicMock())

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routes.odoo_connect import router, _sid_token_store

_VALID_SID      = "test-odoo-session-abc"
_VALID_REDIRECT = "http://localhost:9092/odoo/callback"
_STATE_DATA     = {
    "invite_id":    _VALID_SID,
    "redirect_uri": _VALID_REDIRECT,
    "csrf":         "test-csrf-token",
}
_BEARER_TOKEN   = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.test"


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/odoo")
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


# ── verify-url ────────────────────────────────────────────────────────────────

def test_verify_url_returns_401_when_no_token_in_store():
    """
    When no Bearer token was captured on initiate (token store empty for sid),
    verify-url must return 401 with session_token_missing.
    """
    client = TestClient(_make_app(), raise_server_exceptions=False)

    # Ensure no token stored for this sid
    _sid_token_store.pop(_VALID_SID, None)

    with patch("app.routes.odoo_connect.verify_state", return_value=_STATE_DATA):
        resp = client.post(
            "/api/v1/odoo/connect/verify-url",
            json={"state": "valid-state", "odoo_url": "https://mycompany.odoo.com"},
        )

    assert resp.status_code == 401
    assert resp.json()["error"] == "session_token_missing"


def test_verify_url_forwards_bearer_token_to_orchestrator():
    """
    When a Bearer token is stored for the sid, verify-url must include it
    in the Authorization header sent to the orchestrator.
    """
    client = TestClient(_make_app(), raise_server_exceptions=False)

    # Seed the token store as initiate would
    _sid_token_store[_VALID_SID] = (_BEARER_TOKEN, time.monotonic())

    captured_headers: dict = {}

    orc_resp = MagicMock()
    orc_resp.status_code = 200
    orc_resp.json.return_value = {
        "status": "success",
        "data": ["mydb"],
    }

    async def mock_post(url, json=None, headers=None, **kwargs):
        captured_headers.update(headers or {})
        return orc_resp

    http_cm = AsyncMock()
    http_cm.__aenter__ = AsyncMock(return_value=http_cm)
    http_cm.__aexit__ = AsyncMock(return_value=None)
    http_cm.post = mock_post

    with patch("app.routes.odoo_connect.verify_state", return_value=_STATE_DATA), \
         patch("app.routes.odoo_connect.httpx.AsyncClient", return_value=http_cm):
        resp = client.post(
            "/api/v1/odoo/connect/verify-url",
            json={"state": "valid-state", "odoo_url": "https://mycompany.odoo.com"},
        )

    assert resp.status_code == 200
    assert captured_headers.get("Authorization") == f"Bearer {_BEARER_TOKEN}"
    assert resp.json()["databases"] == ["mydb"]

    # Cleanup
    _sid_token_store.pop(_VALID_SID, None)


def test_verify_url_returns_400_on_invalid_state():
    """Tampered or expired state must return 400 invalid_state."""
    client = TestClient(_make_app(), raise_server_exceptions=False)

    with patch("app.routes.odoo_connect.verify_state", side_effect=ValueError("bad")):
        resp = client.post(
            "/api/v1/odoo/connect/verify-url",
            json={"state": "tampered", "odoo_url": "https://mycompany.odoo.com"},
        )

    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_state"


# ── complete ──────────────────────────────────────────────────────────────────

def test_verify_url_passes_csrf_cookie_to_verify_state():
    """
    verify-url must read the sso_csrf cookie and pass it as cookie_csrf to verify_state.
    If the cookie is present but doesn't match, verify_state raises and we get 400.
    """
    client = TestClient(_make_app(), raise_server_exceptions=False)

    _sid_token_store[_VALID_SID] = (_BEARER_TOKEN, time.monotonic())

    captured: dict = {}

    def capture_verify_state(state, cookie_csrf=None):
        captured["cookie_csrf"] = cookie_csrf
        return _STATE_DATA

    orc_resp = MagicMock()
    orc_resp.status_code = 200
    orc_resp.json.return_value = {"status": "success", "data": ["mydb"]}

    async def mock_post(url, **kwargs):
        return orc_resp

    http_cm = AsyncMock()
    http_cm.__aenter__ = AsyncMock(return_value=http_cm)
    http_cm.__aexit__ = AsyncMock(return_value=None)
    http_cm.post = mock_post

    with patch("app.routes.odoo_connect.verify_state", side_effect=capture_verify_state), \
         patch("app.routes.odoo_connect.httpx.AsyncClient", return_value=http_cm):
        client.post(
            "/api/v1/odoo/connect/verify-url",
            json={"state": "valid-state", "odoo_url": "https://mycompany.odoo.com"},
            cookies={"sso_csrf": "my-csrf-value"},
        )

    assert captured.get("cookie_csrf") == "my-csrf-value"

    _sid_token_store.pop(_VALID_SID, None)


def test_verify_url_csrf_mismatch_returns_400():
    """When the sso_csrf cookie doesn't match the state, verify-url must return 400 invalid_state."""
    client = TestClient(_make_app(), raise_server_exceptions=False)

    _sid_token_store[_VALID_SID] = (_BEARER_TOKEN, time.monotonic())

    with patch("app.routes.odoo_connect.verify_state", side_effect=ValueError("csrf mismatch")):
        resp = client.post(
            "/api/v1/odoo/connect/verify-url",
            json={"state": "valid-state", "odoo_url": "https://mycompany.odoo.com"},
            cookies={"sso_csrf": "wrong-csrf"},
        )

    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_state"

    _sid_token_store.pop(_VALID_SID, None)


def test_complete_redirects_with_session_token_missing_when_no_token():
    """
    complete must redirect to the MCP callback with error=session_token_missing
    when the token store has no entry for the sid (e.g. TTL expired).
    """
    client = TestClient(_make_app(), raise_server_exceptions=False)

    _sid_token_store.pop(_VALID_SID, None)

    with patch("app.routes.odoo_connect.verify_state", return_value=_STATE_DATA):
        resp = client.post(
            "/api/v1/odoo/connect/complete",
            data={
                "state":    "valid-state",
                "odoo_url": "https://mycompany.odoo.com",
                "database": "mydb",
                "username": "admin@example.com",
                "api_key":  "my-api-key",
            },
            follow_redirects=False,
        )

    assert resp.status_code == 302
    assert "error=session_token_missing" in resp.headers["location"]
