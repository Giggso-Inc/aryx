"""
Golden-master / characterization tests for app/routes/sso.py.

Purpose: this file (233 lines, 2 endpoints: GET /{provider}/initiate,
GET /{provider}/callback) has zero existing route-level test coverage
(confirmed via grep across tests/ for "app.routes.sso" before writing this
file — zero hits; tests/test_sso_service_characterization.py exercises
app/services/sso_service/* directly, not the route layer). This is the SSO
login flow — security-critical code, same caution level as auth.py. It is
about to be split per docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md (wave
B5, final wave).

These are characterization tests, not "correctness" tests: assertions
match what the code actually does today, including documented quirks:

  - sso_callback()'s `provider` path param is NOT validated against
    ALLOWED_PROVIDERS the way sso_initiate()'s is — a callback hit with an
    arbitrary provider string (e.g. "yahoo") falls through the
    if/elif/else in the try block to the `else: return
    _fragment_error_redirect(redirect_uri, "unknown_provider")` branch,
    but only AFTER state has already been verified and redirect_uri
    validated — so this is reachable and produces a 302, not a 4xx.
  - Provider-exchange failures are caught by two separate except clauses
    (`except ProviderError` and a catch-all `except Exception`) that both
    do the exact same thing (redirect with "provider_error") — so a
    non-ProviderError exception from exchange_google_code/
    exchange_microsoft_code is indistinguishable from a real ProviderError
    to the client.
  - resolve_sso_user()'s and issue_tokens_for_user()'s generic
    `except Exception` both also collapse to the same "provider_error"
    fragment redirect — a DB error while resolving/creating the user looks
    identical to a real IdP failure from the outside.
  - Early errors (before redirect_uri is trusted: missing/malformed state,
    disallowed redirect_uri) return JSON via `_json_sso_error`, not a
    redirect — only once redirect_uri has been validated does the
    handler switch to fragment-redirect errors via
    `_fragment_error_redirect`. `error=access_denied` from the IdP is the
    one exception: it returns JSON at 403 even though code/state haven't
    been parsed yet.
  - Every error path (both JSON and redirect) deletes the sso_csrf cookie,
    including the final happy-path redirect.

Pattern follows tests/test_auth_routes_characterization.py /
tests/test_user_auth_characterization.py:
- FastAPI TestClient with `app.include_router(router, prefix="/api/v1/sso")`.
- `app.dependency_overrides[get_db] = lambda: mock_db`.
- Every name sso.py imports from app.services.sso_service is imported at
  MODULE level (`from app.services.sso_service import (...)`), so all
  patch targets are `app.routes.sso.<name>` (not the service module).
- `follow_redirects=False` so 302 Location/fragment content can be
  asserted directly instead of chasing the redirect.

Do not modify app/routes/sso.py (or the post-split package) from this
file's tests.
"""

from __future__ import annotations

import base64
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services.sso_service import (
    InvitationNotFoundError,
    InvitationInvalidError,
    SignupInviteRequiredError,
    EmailMismatchError,
    ProviderError,
)


def _make_client(mock_db):
    from app.core.database import get_db
    from app.routes.sso import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/sso")
    app.dependency_overrides[get_db] = lambda: mock_db
    return TestClient(app, raise_server_exceptions=False)


def _decode_fragment_payload(location: str) -> dict:
    frag = location.split("#sso_data=", 1)[1]
    padded = frag + "=" * (-len(frag) % 4)
    return json.loads(base64.urlsafe_b64decode(padded).decode())


_REDIRECT_URI = "https://app.example.com/sso-callback"


def _token_response(**overrides):
    data = {
        "access_token": "access-tok",
        "refresh_token": "refresh-tok",
        "token_type": "bearer",
        "expires_in": 1800,
        "user_id": "user-001",
        "email_id": "user@example.com",
        "name": "Some User",
        "full_name": None,
        "role": "user",
        "company_id": "company-001",
        "company_name": None,
        "default_workspace_id": None,
    }
    data.update(overrides)
    tr = MagicMock()
    tr.model_dump.return_value = data
    return tr


# ===========================================================================
# GET /{provider}/initiate — sso_initiate
# ===========================================================================

class TestSsoInitiate:
    @pytest.mark.unit
    def test_unknown_provider_returns_400_sso_001(self, mock_db):
        client = _make_client(mock_db)
        resp = client.get(
            "/api/v1/sso/facebook/initiate",
            params={"redirect_uri": _REDIRECT_URI},
        )
        assert resp.status_code == 400
        assert resp.json()["detail"]["error_code"] == "SSO_001"

    @pytest.mark.unit
    def test_disallowed_redirect_uri_returns_400_sso_002(self, mock_db):
        client = _make_client(mock_db)
        with patch("app.routes.sso.initiate.is_allowed_redirect_uri", return_value=False):
            resp = client.get(
                "/api/v1/sso/google/initiate",
                params={"redirect_uri": "https://evil.example.com"},
            )
        assert resp.status_code == 400
        assert resp.json()["detail"]["error_code"] == "SSO_002"

    @pytest.mark.unit
    def test_google_happy_path_sets_csrf_cookie_and_returns_auth_url(self, mock_db):
        client = _make_client(mock_db)
        with patch("app.routes.sso.initiate.is_allowed_redirect_uri", return_value=True), \
             patch("app.routes.sso.initiate.build_state", return_value="signed-state-blob"), \
             patch("app.routes.sso.initiate.get_google_authorization_url", return_value="https://accounts.google.com/auth?x=1") as mock_google, \
             patch("app.routes.sso.initiate.get_microsoft_authorization_url") as mock_ms:
            resp = client.get(
                "/api/v1/sso/google/initiate",
                params={"redirect_uri": _REDIRECT_URI},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["authorization_url"] == "https://accounts.google.com/auth?x=1"
        assert body["state"] == "signed-state-blob"
        assert "sso_csrf" in resp.cookies
        mock_google.assert_called_once_with("signed-state-blob")
        mock_ms.assert_not_called()

    @pytest.mark.unit
    def test_microsoft_happy_path_uses_microsoft_auth_url(self, mock_db):
        client = _make_client(mock_db)
        with patch("app.routes.sso.initiate.is_allowed_redirect_uri", return_value=True), \
             patch("app.routes.sso.initiate.build_state", return_value="signed-state-blob"), \
             patch("app.routes.sso.initiate.get_microsoft_authorization_url", return_value="https://login.microsoftonline.com/auth?x=1") as mock_ms:
            resp = client.get(
                "/api/v1/sso/microsoft/initiate",
                params={"redirect_uri": _REDIRECT_URI},
            )
        assert resp.status_code == 200
        assert resp.json()["authorization_url"] == "https://login.microsoftonline.com/auth?x=1"
        mock_ms.assert_called_once_with("signed-state-blob")

    @pytest.mark.unit
    def test_redirect_uri_and_invite_id_are_stripped_before_use(self, mock_db):
        client = _make_client(mock_db)
        captured = {}

        def _fake_build_state(invite_id, redirect_uri, csrf_token):
            captured["invite_id"] = invite_id
            captured["redirect_uri"] = redirect_uri
            return "state"

        with patch("app.routes.sso.initiate.is_allowed_redirect_uri", return_value=True), \
             patch("app.routes.sso.initiate.build_state", side_effect=_fake_build_state), \
             patch("app.routes.sso.initiate.get_google_authorization_url", return_value="url"):
            resp = client.get(
                "/api/v1/sso/google/initiate",
                params={"redirect_uri": f"  {_REDIRECT_URI}  ", "invite_id": "  invite-123  "},
            )
        assert resp.status_code == 200
        assert captured["redirect_uri"] == _REDIRECT_URI
        assert captured["invite_id"] == "invite-123"

    @pytest.mark.unit
    def test_no_invite_id_passes_empty_string_to_build_state(self, mock_db):
        """Current behavior: omitting invite_id (returning-user sign-in)
        embeds an empty string in state, not None."""
        client = _make_client(mock_db)
        captured = {}

        def _fake_build_state(invite_id, redirect_uri, csrf_token):
            captured["invite_id"] = invite_id
            return "state"

        with patch("app.routes.sso.initiate.is_allowed_redirect_uri", return_value=True), \
             patch("app.routes.sso.initiate.build_state", side_effect=_fake_build_state), \
             patch("app.routes.sso.initiate.get_google_authorization_url", return_value="url"):
            resp = client.get(
                "/api/v1/sso/google/initiate",
                params={"redirect_uri": _REDIRECT_URI},
            )
        assert resp.status_code == 200
        assert captured["invite_id"] == ""


# ===========================================================================
# GET /{provider}/callback — sso_callback
# ===========================================================================

class TestSsoCallback:
    @pytest.mark.unit
    def test_idp_denied_access_returns_403_json_and_clears_cookie(self, mock_db):
        client = _make_client(mock_db)
        resp = client.get(
            "/api/v1/sso/google/callback",
            params={"error": "access_denied"},
            follow_redirects=False,
        )
        assert resp.status_code == 403
        body = resp.json()
        assert body["error_code"] == "SSO_003"
        assert "denied access" in body["message"]
        assert 'sso_csrf=""' in resp.headers.get("set-cookie", "")

    @pytest.mark.unit
    def test_missing_state_returns_400_json_invalid_state(self, mock_db):
        client = _make_client(mock_db)
        resp = client.get("/api/v1/sso/google/callback", params={"code": "abc"})
        assert resp.status_code == 400
        assert resp.json()["error_code"] == "SSO_009"

    @pytest.mark.unit
    @pytest.mark.parametrize("bad_state", [
        "somevalue&code=xyz",
        "somevalue&iss=xyz",
        "somevalue%26code%3Dxyz",
        "somevalue%26iss%3Dxyz",
    ])
    def test_malformed_state_with_embedded_provider_params_returns_400(self, mock_db, bad_state):
        """Current behavior: these substring checks run BEFORE verify_state
        is even called, catching callbacks where a provider's query params
        leaked into the state value."""
        client = _make_client(mock_db)
        with patch("app.routes.sso.callback.verify_state") as mock_verify:
            resp = client.get(
                "/api/v1/sso/google/callback",
                params={"code": "abc", "state": bad_state},
            )
        assert resp.status_code == 400
        assert resp.json()["error_code"] == "SSO_009"
        mock_verify.assert_not_called()

    @pytest.mark.unit
    def test_verify_state_value_error_returns_400_invalid_state(self, mock_db):
        client = _make_client(mock_db)
        with patch("app.routes.sso.callback.verify_state", side_effect=ValueError("bad sig")):
            resp = client.get(
                "/api/v1/sso/google/callback",
                params={"code": "abc", "state": "tampered-state"},
            )
        assert resp.status_code == 400
        assert resp.json()["error_code"] == "SSO_009"

    @pytest.mark.unit
    def test_disallowed_redirect_uri_in_state_returns_400_json(self, mock_db):
        """Redirect_uri not yet trusted at this point -> JSON error, not a
        redirect to that untrusted URI."""
        client = _make_client(mock_db)
        with patch("app.routes.sso.callback.verify_state",
                   return_value={"invite_id": "", "redirect_uri": "https://evil.example.com"}), \
             patch("app.routes.sso.callback.is_allowed_redirect_uri", return_value=False):
            resp = client.get(
                "/api/v1/sso/google/callback",
                params={"code": "abc", "state": "good-state"},
            )
        assert resp.status_code == 400
        assert resp.json()["error_code"] == "SSO_002"

    @pytest.mark.unit
    def test_missing_code_redirects_with_provider_error_fragment(self, mock_db):
        client = _make_client(mock_db)
        with patch("app.routes.sso.callback.verify_state",
                   return_value={"invite_id": "", "redirect_uri": _REDIRECT_URI}), \
             patch("app.routes.sso.callback.is_allowed_redirect_uri", return_value=True):
            resp = client.get(
                "/api/v1/sso/google/callback",
                params={"state": "good-state"},
                follow_redirects=False,
            )
        assert resp.status_code == 302
        location = resp.headers["location"]
        assert location.startswith(_REDIRECT_URI + "#")
        assert "SSO_008" in location

    @pytest.mark.unit
    def test_unknown_provider_in_path_redirects_with_unknown_provider_fragment(self, mock_db):
        """sso_callback does not validate `provider` against
        ALLOWED_PROVIDERS the way sso_initiate does -- an arbitrary value
        reaches the else-branch inside the try block."""
        client = _make_client(mock_db)
        with patch("app.routes.sso.callback.verify_state",
                   return_value={"invite_id": "", "redirect_uri": _REDIRECT_URI}), \
             patch("app.routes.sso.callback.is_allowed_redirect_uri", return_value=True):
            resp = client.get(
                "/api/v1/sso/yahoo/callback",
                params={"code": "abc", "state": "good-state"},
                follow_redirects=False,
            )
        assert resp.status_code == 302
        assert "SSO_010" in resp.headers["location"]

    @pytest.mark.unit
    def test_provider_error_during_exchange_redirects_with_provider_error(self, mock_db):
        client = _make_client(mock_db)
        with patch("app.routes.sso.callback.verify_state",
                   return_value={"invite_id": "", "redirect_uri": _REDIRECT_URI}), \
             patch("app.routes.sso.callback.is_allowed_redirect_uri", return_value=True), \
             patch("app.routes.sso.callback.exchange_google_code", new=AsyncMock(side_effect=ProviderError("bad token"))):
            resp = client.get(
                "/api/v1/sso/google/callback",
                params={"code": "abc", "state": "good-state"},
                follow_redirects=False,
            )
        assert resp.status_code == 302
        assert "SSO_008" in resp.headers["location"]

    @pytest.mark.unit
    def test_generic_exception_during_exchange_also_redirects_with_provider_error(self, mock_db):
        """Documented quirk: a non-ProviderError exception (e.g. a bug, a
        timeout) is indistinguishable from a real ProviderError to the
        client -- both hit the same fragment redirect."""
        client = _make_client(mock_db)
        with patch("app.routes.sso.callback.verify_state",
                   return_value={"invite_id": "", "redirect_uri": _REDIRECT_URI}), \
             patch("app.routes.sso.callback.is_allowed_redirect_uri", return_value=True), \
             patch("app.routes.sso.callback.exchange_microsoft_code", new=AsyncMock(side_effect=RuntimeError("boom"))):
            resp = client.get(
                "/api/v1/sso/microsoft/callback",
                params={"code": "abc", "state": "good-state"},
                follow_redirects=False,
            )
        assert resp.status_code == 302
        assert "SSO_008" in resp.headers["location"]

    @pytest.mark.unit
    @pytest.mark.parametrize("exc_cls,error_code", [
        (InvitationNotFoundError, "SSO_005"),
        (InvitationInvalidError, "SSO_006"),
        (SignupInviteRequiredError, "SSO_012"),
        (EmailMismatchError, "SSO_007"),
    ])
    def test_resolve_sso_user_errors_map_to_distinct_fragment_codes(self, mock_db, exc_cls, error_code):
        client = _make_client(mock_db)
        # InvitationNotFoundError/InvitationInvalidError/SignupInviteRequiredError take no
        # constructor args (they hardcode message + error_code); only EmailMismatchError
        # takes a `provider` positional arg. Build each exception instance accordingly.
        exc_instance = exc_cls("google") if exc_cls is EmailMismatchError else exc_cls()
        with patch("app.routes.sso.callback.verify_state",
                   return_value={"invite_id": "", "redirect_uri": _REDIRECT_URI}), \
             patch("app.routes.sso.callback.is_allowed_redirect_uri", return_value=True), \
             patch("app.routes.sso.callback.exchange_google_code", new=AsyncMock(
                 return_value={"google_id": "gid-1", "email": "u@example.com", "name": "U"})), \
             patch("app.routes.sso.callback.resolve_sso_user", new=AsyncMock(side_effect=exc_instance)):
            resp = client.get(
                "/api/v1/sso/google/callback",
                params={"code": "abc", "state": "good-state"},
                follow_redirects=False,
            )
        assert resp.status_code == 302
        assert error_code in resp.headers["location"]

    @pytest.mark.unit
    def test_resolve_sso_user_generic_exception_redirects_with_provider_error(self, mock_db):
        client = _make_client(mock_db)
        with patch("app.routes.sso.callback.verify_state",
                   return_value={"invite_id": "", "redirect_uri": _REDIRECT_URI}), \
             patch("app.routes.sso.callback.is_allowed_redirect_uri", return_value=True), \
             patch("app.routes.sso.callback.exchange_google_code", new=AsyncMock(
                 return_value={"google_id": "gid-1", "email": "u@example.com", "name": "U"})), \
             patch("app.routes.sso.callback.resolve_sso_user", new=AsyncMock(side_effect=RuntimeError("db down"))):
            resp = client.get(
                "/api/v1/sso/google/callback",
                params={"code": "abc", "state": "good-state"},
                follow_redirects=False,
            )
        assert resp.status_code == 302
        assert "SSO_008" in resp.headers["location"]

    @pytest.mark.unit
    def test_issue_tokens_exception_redirects_with_provider_error(self, mock_db):
        client = _make_client(mock_db)
        fake_user = MagicMock()
        with patch("app.routes.sso.callback.verify_state",
                   return_value={"invite_id": "", "redirect_uri": _REDIRECT_URI}), \
             patch("app.routes.sso.callback.is_allowed_redirect_uri", return_value=True), \
             patch("app.routes.sso.callback.exchange_google_code", new=AsyncMock(
                 return_value={"google_id": "gid-1", "email": "u@example.com", "name": "U"})), \
             patch("app.routes.sso.callback.resolve_sso_user", new=AsyncMock(return_value=fake_user)), \
             patch("app.routes.sso.callback.issue_tokens_for_user", new=AsyncMock(side_effect=RuntimeError("token issuance failed"))):
            resp = client.get(
                "/api/v1/sso/google/callback",
                params={"code": "abc", "state": "good-state"},
                follow_redirects=False,
            )
        assert resp.status_code == 302
        assert "SSO_008" in resp.headers["location"]

    @pytest.mark.unit
    def test_happy_path_google_redirects_with_base64_sso_data_fragment(self, mock_db):
        client = _make_client(mock_db)
        fake_user = MagicMock()
        token_resp = _token_response(company_name="Acme Inc", default_workspace_id="ws-1")
        with patch("app.routes.sso.callback.verify_state",
                   return_value={"invite_id": "", "redirect_uri": _REDIRECT_URI}), \
             patch("app.routes.sso.callback.is_allowed_redirect_uri", return_value=True), \
             patch("app.routes.sso.callback.exchange_google_code", new=AsyncMock(
                 return_value={"google_id": "gid-1", "email": "u@example.com",
                               "name": "U", "avatar_url": "https://x/pic.png"})), \
             patch("app.routes.sso.callback.resolve_sso_user", new=AsyncMock(return_value=fake_user)), \
             patch("app.routes.sso.callback.issue_tokens_for_user", new=AsyncMock(return_value=token_resp)):
            resp = client.get(
                "/api/v1/sso/google/callback",
                params={"code": "abc", "state": "good-state"},
                follow_redirects=False,
            )
        assert resp.status_code == 302
        location = resp.headers["location"]
        assert location.startswith(_REDIRECT_URI + "#sso_data=")
        payload = _decode_fragment_payload(location)
        assert payload["access_token"] == "access-tok"
        assert payload["refresh_token"] == "refresh-tok"
        assert payload["user_id"] == "user-001"
        # _TOKEN_FIELDS in sso.py's callback does not include "company_name" or
        # "default_workspace_id" -- only the fixed set of fields it whitelists
        # ever makes it into the fragment, regardless of what token_response
        # carries. Both keys are therefore always absent, not just when None.
        assert "company_name" not in payload
        assert "default_workspace_id" not in payload
        # None-valued fields are dropped, and fields outside _TOKEN_FIELDS
        # (there are none extra here, but full_name was None) are excluded:
        assert "full_name" not in payload
        assert 'sso_csrf=""' in resp.headers.get("set-cookie", "")

    @pytest.mark.unit
    def test_happy_path_microsoft_uses_microsoft_id_field(self, mock_db):
        client = _make_client(mock_db)
        fake_user = MagicMock()
        token_resp = _token_response()
        captured = {}

        async def _fake_resolve(**kwargs):
            captured.update(kwargs)
            return fake_user

        with patch("app.routes.sso.callback.verify_state",
                   return_value={"invite_id": "invite-abc", "redirect_uri": _REDIRECT_URI}), \
             patch("app.routes.sso.callback.is_allowed_redirect_uri", return_value=True), \
             patch("app.routes.sso.callback.exchange_microsoft_code", new=AsyncMock(
                 return_value={"microsoft_id": "mid-1", "email": "u2@example.com", "name": "U2"})), \
             patch("app.routes.sso.callback.resolve_sso_user", new=_fake_resolve), \
             patch("app.routes.sso.callback.issue_tokens_for_user", new=AsyncMock(return_value=token_resp)):
            resp = client.get(
                "/api/v1/sso/microsoft/callback",
                params={"code": "abc", "state": "good-state"},
                follow_redirects=False,
            )
        assert resp.status_code == 302
        assert captured["provider_id_field"] == "microsoft_id"
        assert captured["provider_id_value"] == "mid-1"
        assert captured["provider_name"] == "microsoft"
        assert captured["invite_id"] == "invite-abc"
