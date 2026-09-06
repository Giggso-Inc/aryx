"""
Golden-master / characterization tests for app/routes/auth.py.

Purpose: this file (312 lines, 7 endpoints: POST /login, POST /callback,
POST /refresh, GET /me, POST /logout, PUT /me, POST /dev-token) has zero
existing route-level test coverage (confirmed via grep across tests/ for
"app.routes.auth" and "app.routes.sso" before writing this file — zero
hits). It is core login/token/authentication logic and is about to be split
per docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md (wave B5, final wave).

Extreme caution: a subtle behavior change here could silently break
authentication for the whole app. These are characterization tests, not
"correctness" tests — assertions match what the code actually does today,
bugs included and documented inline where found:

  - refresh_token(): the endpoint's own `raise HTTPException(401, "Invalid
    refresh token")` for a bad/missing-type token is caught by its own
    `except Exception as e:` (HTTPException IS an Exception) and re-wrapped
    into a NEW HTTPException with detail
    f"Token refresh failed: {str(e)}" — so the client sees
    "Token refresh failed: 401: Invalid refresh token", not the bare
    "Invalid refresh token" message. Any exception from verify_token() or
    create_access_token() is wrapped the same way.
  - get_current_user_info() / update_current_user(): both call
    `get_current_user_required(request)` WITHOUT passing `db` even though
    `db` is injected as a route dependency — so the email-verification
    fallback path inside get_current_user_required opens its OWN db
    session via `get_db()` rather than reusing the route's session. Not
    observable from outside (mocked away here), but noted for the record.
  - oauth_callback(): any exception anywhere in the whole try block
    (network, missing dict key, DB error, ...) is flattened into a single
    generic 400 "OAuth callback failed: {str(e)}" — there is no
    distinction between "Google is down" and "malformed profile payload".
  - logout(): does not do anything with logout_data.refresh_token at all
    (no blacklisting) — always returns the same static success message,
    even for a garbage/empty token.

Pattern follows tests/test_user_auth_characterization.py:
- FastAPI TestClient with `app.include_router(router, prefix="/api/v1/auth")`.
- `app.dependency_overrides[get_db] = lambda: mock_db`.
- AsyncMock/MagicMock for DB session and external calls; no real DB, no
  real HTTP (httpx.AsyncClient is patched per
  tests/test_gmail_connect.py's `_make_httpx_side_effect` pattern).
- Real ID generators (uuid4-based, app.core.auth.ids) and real
  create_access_token/create_refresh_token/create_token_data are used
  un-mocked (they have real defaults via app.core.config.settings, no
  .env required) so encode/decode round trips are exercised for real.

Do not modify app/routes/auth.py (or the post-split package) from this
file's tests.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from datetime import datetime

from jose import jwt

from app.core.config import settings


def _scalar_result(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _count_result(value):
    result = MagicMock()
    result.scalar.return_value = value
    return result


def _make_client(mock_db):
    from app.core.database import get_db
    from app.routes.auth import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/auth")
    app.dependency_overrides[get_db] = lambda: mock_db
    return TestClient(app, raise_server_exceptions=False)


def _make_httpx_side_effect(*resps):
    """Return side_effect list for httpx.AsyncClient: each call yields next
    context manager. Mirrors tests/test_gmail_connect.py's helper — one
    entry per `async with httpx.AsyncClient() as client:` block."""
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


def _http_resp(json_data, raise_exc=None):
    resp = MagicMock()
    resp.json.return_value = json_data
    if raise_exc:
        resp.raise_for_status.side_effect = raise_exc
    else:
        resp.raise_for_status.return_value = None
    return resp


# ===========================================================================
# POST /login — login (initiate Google OAuth2)
# ===========================================================================

class TestLogin:
    @pytest.mark.unit
    def test_happy_path_returns_google_auth_url(self, mock_db):
        client = _make_client(mock_db)
        resp = client.post("/api/v1/auth/login", json={"provider": "google"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["message"] == "Redirect to Google OAuth"
        assert body["auth_url"].startswith("https://accounts.google.com/o/oauth2/v2/auth?")
        assert f"client_id={settings.GOOGLE_CLIENT_ID}" in body["auth_url"]
        assert f"redirect_uri={settings.GOOGLE_REDIRECT_URI}" in body["auth_url"]
        assert "scope=openid email profile" in body["auth_url"]

    @pytest.mark.unit
    def test_request_body_fields_are_ignored_ie_always_google(self, mock_db):
        """Current behavior: OAuthLogin.provider/redirect_uri are accepted
        by the schema but never read by the handler — the auth_url is
        always built from settings.GOOGLE_CLIENT_ID/GOOGLE_REDIRECT_URI
        regardless of what the client sends."""
        client = _make_client(mock_db)
        resp = client.post(
            "/api/v1/auth/login",
            json={"provider": "microsoft", "redirect_uri": "https://evil.example.com"},
        )
        assert resp.status_code == 200
        assert "evil.example.com" not in resp.json()["auth_url"]


# ===========================================================================
# POST /callback — oauth_callback
# ===========================================================================

class TestOAuthCallback:
    @pytest.mark.unit
    def test_token_exchange_failure_returns_400(self, mock_db):
        client = _make_client(mock_db)
        token_resp = _http_resp({}, raise_exc=RuntimeError("bad token request"))
        mocks = _make_httpx_side_effect((token_resp, "post"))
        with patch("app.routes.auth.callback.httpx.AsyncClient", side_effect=mocks):
            resp = client.post("/api/v1/auth/callback", json={"code": "abc"})
        assert resp.status_code == 400
        assert "OAuth callback failed: bad token request" in resp.json()["detail"]

    @pytest.mark.unit
    def test_new_user_new_company_first_user_becomes_admin(self, mock_db):
        client = _make_client(mock_db)
        token_resp = _http_resp({"access_token": "google-access-tok"})
        profile_resp = _http_resp({
            "id": "google-uid-1",
            "email": "newperson@newco.com",
            "name": "New Person",
            "picture": "https://pic.example.com/a.png",
        })
        mocks = _make_httpx_side_effect((token_resp, "post"), (profile_resp, "get"))

        mock_db.execute = AsyncMock(
            side_effect=[
                _scalar_result(None),   # existing user by google_id -> none
                _scalar_result(None),   # existing company by domain -> none
                _count_result(0),       # user count in new company -> 0 -> admin
            ]
        )
        mock_db.flush = AsyncMock()

        with patch("app.routes.auth.callback.httpx.AsyncClient", side_effect=mocks):
            resp = client.post("/api/v1/auth/callback", json={"code": "abc"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["email"] == "newperson@newco.com"
        assert body["role"] == "admin"
        assert body["expires_in"] == settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
        assert body["access_token"]
        assert body["refresh_token"]
        decoded = jwt.decode(body["access_token"], settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        assert decoded["email"] == "newperson@newco.com"
        assert decoded["role"] == "admin"
        mock_db.add.assert_called()
        mock_db.commit.assert_awaited()

    @pytest.mark.unit
    def test_new_user_existing_company_non_first_user_gets_user_role(self, mock_db):
        client = _make_client(mock_db)
        token_resp = _http_resp({"access_token": "google-access-tok"})
        profile_resp = _http_resp({
            "id": "google-uid-2",
            "email": "second@existingco.com",
            "name": "Second Person",
        })
        mocks = _make_httpx_side_effect((token_resp, "post"), (profile_resp, "get"))

        existing_company = MagicMock()
        existing_company.id = "company-existing-001"
        mock_db.execute = AsyncMock(
            side_effect=[
                _scalar_result(None),              # existing user by google_id -> none
                _scalar_result(existing_company),   # existing company by domain -> found
                _count_result(3),                   # user count -> not first -> "user"
            ]
        )

        with patch("app.routes.auth.callback.httpx.AsyncClient", side_effect=mocks):
            resp = client.post("/api/v1/auth/callback", json={"code": "abc"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["role"] == "user"
        assert body["company_id"] == "company-existing-001"

    @pytest.mark.unit
    def test_new_user_email_with_no_domain_skips_company_lookup(self, mock_db):
        """Current behavior: when the Google profile email has no '@', a
        new Company is created with domain=None without ever querying for
        an existing company by domain (the `if email_domain:` guard skips
        the lookup entirely) — only 2 db.execute calls happen instead of 3."""
        client = _make_client(mock_db)
        token_resp = _http_resp({"access_token": "google-access-tok"})
        profile_resp = _http_resp({
            "id": "google-uid-3",
            "email": "no-at-sign-email",
            "name": "Weird Person",
        })
        mocks = _make_httpx_side_effect((token_resp, "post"), (profile_resp, "get"))

        mock_db.execute = AsyncMock(
            side_effect=[
                _scalar_result(None),  # existing user -> none
                _count_result(0),      # user count in brand-new company -> 0 -> admin
            ]
        )
        mock_db.flush = AsyncMock()

        with patch("app.routes.auth.callback.httpx.AsyncClient", side_effect=mocks):
            resp = client.post("/api/v1/auth/callback", json={"code": "abc"})

        assert resp.status_code == 200
        assert mock_db.execute.await_count == 2

    @pytest.mark.unit
    def test_existing_user_updates_last_login_and_reuses_role(self, mock_db):
        client = _make_client(mock_db)
        token_resp = _http_resp({"access_token": "google-access-tok"})
        profile_resp = _http_resp({
            "id": "google-uid-existing",
            "email": "existing@co.com",
            "name": "Existing Person",
        })
        mocks = _make_httpx_side_effect((token_resp, "post"), (profile_resp, "get"))

        existing_user = MagicMock()
        existing_user.id = "user-existing-001"
        existing_user.email_id = "existing@co.com"
        existing_user.role = "user"
        existing_user.company_id = "company-001"
        existing_user.last_login = None
        mock_db.execute = AsyncMock(side_effect=[_scalar_result(existing_user)])

        with patch("app.routes.auth.callback.httpx.AsyncClient", side_effect=mocks):
            resp = client.post("/api/v1/auth/callback", json={"code": "abc"})

        assert resp.status_code == 200
        assert mock_db.execute.await_count == 1
        assert existing_user.last_login is not None
        mock_db.commit.assert_awaited()
        assert resp.json()["user_id"] == "user-existing-001"


# ===========================================================================
# POST /refresh — refresh_token
# ===========================================================================

class TestRefreshToken:
    @pytest.mark.unit
    def test_invalid_type_wrapped_in_generic_500_style_message(self, mock_db):
        """Current behavior (documented bug): the endpoint's own 401 raise
        for an invalid/missing-type token is caught by its own blanket
        `except Exception` and re-wrapped as
        'Token refresh failed: 401: Invalid refresh token'. Status code
        stays 401 (the except clause always raises with 401), but the
        detail text no longer reads as the original message alone."""
        client = _make_client(mock_db)
        with patch("app.core.auth.verify_token", return_value={"sub": "u1", "type": "access"}):
            resp = client.post("/api/v1/auth/refresh", json={"refresh_token": "sometoken"})
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Token refresh failed: 401: Invalid refresh token"

    @pytest.mark.unit
    def test_verify_token_returns_none_same_wrapped_message(self, mock_db):
        client = _make_client(mock_db)
        with patch("app.core.auth.verify_token", return_value=None):
            resp = client.post("/api/v1/auth/refresh", json={"refresh_token": "sometoken"})
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Token refresh failed: 401: Invalid refresh token"

    @pytest.mark.unit
    def test_verify_token_raises_is_also_wrapped(self, mock_db):
        client = _make_client(mock_db)
        with patch("app.core.auth.verify_token", side_effect=RuntimeError("decode boom")):
            resp = client.post("/api/v1/auth/refresh", json={"refresh_token": "sometoken"})
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Token refresh failed: decode boom"

    @pytest.mark.unit
    def test_happy_path_returns_new_access_token_and_echoes_refresh_token(self, mock_db):
        client = _make_client(mock_db)
        payload = {
            "sub": "user-001",
            "email": "user@example.com",
            "role": "admin",
            "company_id": "company-001",
            "type": "refresh",
        }
        with patch("app.core.auth.verify_token", return_value=payload):
            resp = client.post("/api/v1/auth/refresh", json={"refresh_token": "the-original-refresh-token"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["refresh_token"] == "the-original-refresh-token"
        assert body["user_id"] == "user-001"
        assert body["email"] == "user@example.com"
        assert body["role"] == "admin"
        assert body["company_id"] == "company-001"
        assert body["expires_in"] == settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
        decoded = jwt.decode(body["access_token"], settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        assert decoded["type"] == "access"


# ===========================================================================
# GET /me — get_current_user_info
# ===========================================================================

class TestGetCurrentUserInfo:
    @pytest.mark.unit
    def test_happy_path_returns_user_response(self, mock_db, admin_user):
        admin_user.created_datetime = datetime.utcnow()
        admin_user.updated_datetime = datetime.utcnow()
        admin_user.last_login = None
        admin_user.is_active = True
        client = _make_client(mock_db)
        with patch("app.middleware.auth_middleware.get_current_user_required",
                   new=AsyncMock(return_value=admin_user)):
            resp = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer tok"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["email_id"] == admin_user.email_id
        assert body["role"] == "admin"

    @pytest.mark.unit
    def test_unauthenticated_propagates_401(self, mock_db):
        """get_current_user_info() has no try/except of its own — an
        HTTPException raised by get_current_user_required() propagates
        unchanged (unlike oauth_callback/refresh_token, which both wrap
        exceptions)."""
        from fastapi import HTTPException

        client = _make_client(mock_db)
        with patch(
            "app.middleware.auth_middleware.get_current_user_required",
            new=AsyncMock(side_effect=HTTPException(status_code=401, detail="Authentication required")),
        ):
            resp = client.get("/api/v1/auth/me")
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Authentication required"


# ===========================================================================
# POST /logout — logout
# ===========================================================================

class TestLogout:
    @pytest.mark.unit
    def test_always_returns_success_regardless_of_token_value(self, mock_db):
        """Current behavior (documented): no blacklisting occurs; any
        string (even garbage) in refresh_token yields the same success
        message."""
        client = _make_client(mock_db)
        resp = client.post("/api/v1/auth/logout", json={"refresh_token": "not-a-real-token"})
        assert resp.status_code == 200
        assert resp.json() == {"message": "Successfully logged out"}


# ===========================================================================
# PUT /me — update_current_user
# ===========================================================================

class TestUpdateCurrentUser:
    @pytest.mark.unit
    def test_happy_path_updates_only_set_fields(self, mock_db, admin_user):
        admin_user.created_datetime = datetime.utcnow()
        admin_user.updated_datetime = datetime.utcnow()
        admin_user.last_login = None
        admin_user.is_active = True
        admin_user.preferences = None
        client = _make_client(mock_db)
        with patch("app.middleware.auth_middleware.get_current_user_required",
                   new=AsyncMock(return_value=admin_user)):
            resp = client.put(
                "/api/v1/auth/me",
                json={"name": "Updated Name"},
                headers={"Authorization": "Bearer tok"},
            )
        assert resp.status_code == 200
        assert admin_user.name == "Updated Name"
        mock_db.commit.assert_awaited()
        mock_db.refresh.assert_awaited_with(admin_user)

    @pytest.mark.unit
    def test_unset_fields_are_not_touched(self, mock_db, admin_user):
        """UserUpdate.dict(exclude_unset=True) means fields the client did
        not send are never assigned — e.g. sending only `role` leaves
        `name`/`avatar_url` untouched."""
        admin_user.created_datetime = datetime.utcnow()
        admin_user.updated_datetime = datetime.utcnow()
        admin_user.last_login = None
        admin_user.is_active = True
        original_name = admin_user.name
        client = _make_client(mock_db)
        with patch("app.middleware.auth_middleware.get_current_user_required",
                   new=AsyncMock(return_value=admin_user)):
            resp = client.put(
                "/api/v1/auth/me",
                json={"role": "user"},
                headers={"Authorization": "Bearer tok"},
            )
        assert resp.status_code == 200
        assert admin_user.name == original_name
        assert admin_user.role == "user"


# ===========================================================================
# POST /dev-token — get_dev_token
# ===========================================================================

class TestGetDevToken:
    @pytest.mark.unit
    def test_existing_dev_user_reused(self, mock_db):
        client = _make_client(mock_db)
        dev_user = MagicMock()
        dev_user.id = "dev-user-001"
        dev_user.email_id = "dev@test.com"
        dev_user.role = "admin"
        dev_user.company_id = "dev-company-001"
        mock_db.execute = AsyncMock(side_effect=[_scalar_result(dev_user)])

        resp = client.post("/api/v1/auth/dev-token")
        assert resp.status_code == 200
        body = resp.json()
        assert body["user_id"] == "dev-user-001"
        assert body["email"] == "dev@test.com"
        mock_db.add.assert_not_called()
        assert mock_db.execute.await_count == 1

    @pytest.mark.unit
    def test_no_dev_user_no_dev_company_creates_both(self, mock_db):
        client = _make_client(mock_db)
        mock_db.execute = AsyncMock(
            side_effect=[
                _scalar_result(None),  # dev user lookup -> none
                _scalar_result(None),  # dev company lookup -> none
            ]
        )

        resp = client.post("/api/v1/auth/dev-token")
        assert resp.status_code == 200
        body = resp.json()
        assert body["email"] == "dev@test.com"
        assert body["role"] == "admin"
        assert mock_db.add.call_count == 2  # company then user
        mock_db.commit.assert_awaited()

    @pytest.mark.unit
    def test_no_dev_user_but_dev_company_exists_reuses_company(self, mock_db):
        client = _make_client(mock_db)
        existing_company = MagicMock()
        existing_company.id = "dev-company-existing"
        mock_db.execute = AsyncMock(
            side_effect=[
                _scalar_result(None),             # dev user lookup -> none
                _scalar_result(existing_company),  # dev company lookup -> found
            ]
        )

        resp = client.post("/api/v1/auth/dev-token")
        assert resp.status_code == 200
        body = resp.json()
        assert body["company_id"] == "dev-company-existing"
        assert mock_db.add.call_count == 1  # only the user, company reused
