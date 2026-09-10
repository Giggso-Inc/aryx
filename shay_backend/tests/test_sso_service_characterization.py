"""
Golden-master / characterization tests for app/services/sso_service.py.

Purpose: this file had ZERO dedicated test coverage before this pass. It is
about to be split into a package (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Before the split, we capture
the CURRENT observable behavior of every public function so the split can be
verified to change nothing.

These are characterization tests, not "correctness" tests: assertions match
what the code actually does today, bugs included.

Pattern follows tests/test_channels_characterization.py: no real DB, mock_db
AsyncMock, `asyncio.run()` instead of pytest-asyncio (no async plugin
installed), and `unittest.mock.patch` at the exact import path used inside
the module under test.

Do not modify app/services/sso_service.py from this file's tests.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


MODPATH = "app.services.sso_service"


def _mock_db():
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


class _FakeResult:
    def __init__(self, scalar_one_or_none=None):
        self._son = scalar_one_or_none

    def scalar_one_or_none(self):
        return self._son


# ---------------------------------------------------------------------------
# SSOError hierarchy
# ---------------------------------------------------------------------------

def test_invitation_not_found_error_code():
    from app.services.sso_service import InvitationNotFoundError
    err = InvitationNotFoundError()
    assert err.error_code == "SSO_005"
    assert err.message == "Invitation not found"


def test_invitation_invalid_error_code():
    from app.services.sso_service import InvitationInvalidError
    err = InvitationInvalidError()
    assert err.error_code == "SSO_006"


def test_signup_invite_required_error_code():
    from app.services.sso_service import SignupInviteRequiredError
    err = SignupInviteRequiredError()
    assert err.error_code == "SSO_012"


def test_email_mismatch_error_includes_provider():
    from app.services.sso_service import EmailMismatchError
    err = EmailMismatchError("Google")
    assert err.error_code == "SSO_007"
    assert "Google" in err.message


def test_provider_error_message_format():
    from app.services.sso_service import ProviderError
    err = ProviderError("Microsoft")
    assert err.error_code == "SSO_008"
    assert err.message == "Failed to authenticate with Microsoft"


# ---------------------------------------------------------------------------
# build_state / verify_state
# ---------------------------------------------------------------------------

def test_build_state_and_verify_state_round_trip():
    from app.services.sso_service import build_state, verify_state
    with patch(f"{MODPATH}.state.settings") as mock_settings:
        mock_settings.SSO_STATE_SECRET = "test-secret"
        state = build_state("invite-1", "https://app.example.com/cb", "csrf-abc")
        payload = verify_state(state, cookie_csrf="csrf-abc")
    assert payload == {
        "invite_id": "invite-1",
        "redirect_uri": "https://app.example.com/cb",
        "csrf": "csrf-abc",
    }


def test_verify_state_without_cookie_csrf_still_valid():
    """cookie_csrf is optional — Microsoft's redirect chain can drop it."""
    from app.services.sso_service import build_state, verify_state
    with patch(f"{MODPATH}.state.settings") as mock_settings:
        mock_settings.SSO_STATE_SECRET = "test-secret"
        state = build_state("invite-1", "https://app.example.com/cb", "csrf-abc")
        payload = verify_state(state, cookie_csrf=None)
    assert payload["csrf"] == "csrf-abc"


def test_verify_state_wrong_cookie_csrf_raises():
    from app.services.sso_service import build_state, verify_state
    with patch(f"{MODPATH}.state.settings") as mock_settings:
        mock_settings.SSO_STATE_SECRET = "test-secret"
        state = build_state("invite-1", "https://app.example.com/cb", "csrf-abc")
        with pytest.raises(ValueError, match="Invalid state"):
            verify_state(state, cookie_csrf="wrong-csrf")


def test_verify_state_tampered_signature_raises():
    from app.services.sso_service import build_state, verify_state
    with patch(f"{MODPATH}.state.settings") as mock_settings:
        mock_settings.SSO_STATE_SECRET = "test-secret"
        state = build_state("invite-1", "https://app.example.com/cb", "csrf-abc")
    with patch(f"{MODPATH}.state.settings") as mock_settings:
        mock_settings.SSO_STATE_SECRET = "different-secret"
        with pytest.raises(ValueError, match="Invalid state"):
            verify_state(state)


def test_verify_state_garbage_input_raises():
    from app.services.sso_service import verify_state
    with pytest.raises(ValueError, match="Invalid state"):
        verify_state("not-valid-base64!!!")


# ---------------------------------------------------------------------------
# is_allowed_redirect_uri
# ---------------------------------------------------------------------------

def test_is_allowed_redirect_uri_wildcard():
    from app.services.sso_service import is_allowed_redirect_uri
    with patch(f"{MODPATH}.state.settings") as mock_settings:
        mock_settings.ALLOWED_ORIGINS = ["*"]
        assert is_allowed_redirect_uri("https://anything.example.com/cb") is True


def test_is_allowed_redirect_uri_exact_match():
    from app.services.sso_service import is_allowed_redirect_uri
    with patch(f"{MODPATH}.state.settings") as mock_settings:
        mock_settings.ALLOWED_ORIGINS = ["https://app.example.com"]
        assert is_allowed_redirect_uri("https://app.example.com/some/path") is True


def test_is_allowed_redirect_uri_not_in_list():
    from app.services.sso_service import is_allowed_redirect_uri
    with patch(f"{MODPATH}.state.settings") as mock_settings:
        mock_settings.ALLOWED_ORIGINS = ["https://app.example.com"]
        assert is_allowed_redirect_uri("https://evil.example.com/cb") is False


def test_is_allowed_redirect_uri_missing_scheme_returns_false():
    from app.services.sso_service import is_allowed_redirect_uri
    with patch(f"{MODPATH}.state.settings") as mock_settings:
        mock_settings.ALLOWED_ORIGINS = ["*"]
        assert is_allowed_redirect_uri("not-a-url") is False


# ---------------------------------------------------------------------------
# authorization URL builders
# ---------------------------------------------------------------------------

def test_get_google_authorization_url_contains_expected_params():
    from app.services.sso_service import get_google_authorization_url
    with patch(f"{MODPATH}.google.settings") as mock_settings:
        mock_settings.GOOGLE_CLIENT_ID = "gclient"
        mock_settings.GOOGLE_REDIRECT_URI = "https://app.example.com/google/cb"
        url = get_google_authorization_url("state123")
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "client_id=gclient" in url
    assert "state=state123" in url


def test_get_microsoft_authorization_url_contains_tenant():
    from app.services.sso_service import get_microsoft_authorization_url
    with patch(f"{MODPATH}.microsoft.settings") as mock_settings:
        mock_settings.MICROSOFT_TENANT_ID = "tenant-xyz"
        mock_settings.MICROSOFT_CLIENT_ID = "msclient"
        mock_settings.MICROSOFT_REDIRECT_URI = "https://app.example.com/ms/cb"
        url = get_microsoft_authorization_url("state456")
    assert "tenant-xyz" in url
    assert "client_id=msclient" in url
    assert "state=state456" in url


# ---------------------------------------------------------------------------
# exchange_google_code / exchange_microsoft_code
# ---------------------------------------------------------------------------

def test_exchange_google_code_success():
    from app.services.sso_service import exchange_google_code

    fake_client = AsyncMock()
    token_resp = MagicMock(status_code=200)
    token_resp.json = MagicMock(return_value={"id_token": "fake.jwt.token"})
    jwks_resp = MagicMock(status_code=200)
    jwks_resp.json = MagicMock(return_value={"keys": [{"kid": "kid1"}]})
    fake_client.post = AsyncMock(return_value=token_resp)
    fake_client.get = AsyncMock(return_value=jwks_resp)
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)

    with patch(f"{MODPATH}.google.settings") as mock_settings, \
         patch(f"{MODPATH}.google.httpx.AsyncClient", return_value=fake_client), \
         patch(f"{MODPATH}.google.jwt.get_unverified_header", return_value={"kid": "kid1"}), \
         patch(f"{MODPATH}.google.jwt.decode", return_value={
             "sub": "google-sub-1", "email": "user@example.com", "name": "Jane", "picture": "http://pic"
         }):
        mock_settings.GOOGLE_CLIENT_ID = "gclient"
        mock_settings.GOOGLE_CLIENT_SECRET = "gsecret"
        mock_settings.GOOGLE_REDIRECT_URI = "https://app.example.com/google/cb"

        result = asyncio.run(exchange_google_code("auth-code-1"))

    assert result == {
        "google_id": "google-sub-1",
        "email": "user@example.com",
        "name": "Jane",
        "avatar_url": "http://pic",
    }


def test_exchange_google_code_token_endpoint_failure_raises_provider_error():
    from app.services.sso_service import exchange_google_code, ProviderError

    fake_client = AsyncMock()
    token_resp = MagicMock(status_code=400)
    fake_client.post = AsyncMock(return_value=token_resp)
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)

    with patch(f"{MODPATH}.google.settings") as mock_settings, \
         patch(f"{MODPATH}.google.httpx.AsyncClient", return_value=fake_client):
        mock_settings.GOOGLE_CLIENT_ID = "gclient"
        mock_settings.GOOGLE_CLIENT_SECRET = "gsecret"
        mock_settings.GOOGLE_REDIRECT_URI = "https://app.example.com/google/cb"

        with pytest.raises(ProviderError):
            asyncio.run(exchange_google_code("auth-code-1"))


def test_exchange_microsoft_code_success():
    from app.services.sso_service import exchange_microsoft_code

    fake_client = AsyncMock()
    token_resp = MagicMock(status_code=200)
    token_resp.json = MagicMock(return_value={"access_token": "ms-access"})
    graph_resp = MagicMock(status_code=200)
    graph_resp.json = MagicMock(return_value={
        "id": "ms-id-1", "mail": "user@example.com", "displayName": "Jane Doe"
    })
    fake_client.post = AsyncMock(return_value=token_resp)
    fake_client.get = AsyncMock(return_value=graph_resp)
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)

    with patch(f"{MODPATH}.google.settings") as mock_settings, \
         patch(f"{MODPATH}.google.httpx.AsyncClient", return_value=fake_client):
        mock_settings.MICROSOFT_TENANT_ID = "tenant-xyz"
        mock_settings.MICROSOFT_CLIENT_ID = "msclient"
        mock_settings.MICROSOFT_CLIENT_SECRET = "mssecret"
        mock_settings.MICROSOFT_REDIRECT_URI = "https://app.example.com/ms/cb"

        result = asyncio.run(exchange_microsoft_code("auth-code-2"))

    assert result == {
        "microsoft_id": "ms-id-1",
        "email": "user@example.com",
        "name": "Jane Doe",
        "avatar_url": None,
    }


def test_exchange_microsoft_code_no_email_raises_provider_error():
    from app.services.sso_service import exchange_microsoft_code, ProviderError

    fake_client = AsyncMock()
    token_resp = MagicMock(status_code=200)
    token_resp.json = MagicMock(return_value={"access_token": "ms-access"})
    graph_resp = MagicMock(status_code=200)
    graph_resp.json = MagicMock(return_value={"id": "ms-id-1"})
    fake_client.post = AsyncMock(return_value=token_resp)
    fake_client.get = AsyncMock(return_value=graph_resp)
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)

    with patch(f"{MODPATH}.google.settings") as mock_settings, \
         patch(f"{MODPATH}.google.httpx.AsyncClient", return_value=fake_client):
        mock_settings.MICROSOFT_TENANT_ID = "tenant-xyz"
        mock_settings.MICROSOFT_CLIENT_ID = "msclient"
        mock_settings.MICROSOFT_CLIENT_SECRET = "mssecret"
        mock_settings.MICROSOFT_REDIRECT_URI = "https://app.example.com/ms/cb"

        with pytest.raises(ProviderError):
            asyncio.run(exchange_microsoft_code("auth-code-2"))


# ---------------------------------------------------------------------------
# resolve_sso_user
# ---------------------------------------------------------------------------

def test_resolve_sso_user_returning_by_provider_id():
    from app.services.sso_service import resolve_sso_user

    db = _mock_db()
    provider_user = MagicMock(id=uuid.uuid4())
    db.execute = AsyncMock(side_effect=[
        _FakeResult(scalar_one_or_none=provider_user),
        _FakeResult(scalar_one_or_none=provider_user),
    ])

    result = asyncio.run(resolve_sso_user(
        db, "google_id", "gid-1", "user@example.com", "Jane", None, "", "google",
    ))

    assert result is provider_user
    assert provider_user.last_login is not None
    db.commit.assert_awaited()
    db.refresh.assert_awaited_with(provider_user)


def test_resolve_sso_user_provider_email_mismatch_raises():
    from app.services.sso_service import resolve_sso_user, ProviderError

    db = _mock_db()
    provider_user = MagicMock(id=uuid.uuid4())
    email_user = MagicMock(id=uuid.uuid4())
    db.execute = AsyncMock(side_effect=[
        _FakeResult(scalar_one_or_none=provider_user),
        _FakeResult(scalar_one_or_none=email_user),
    ])

    with pytest.raises(ProviderError):
        asyncio.run(resolve_sso_user(
            db, "google_id", "gid-1", "user@example.com", "Jane", None, "", "google",
        ))


def test_resolve_sso_user_returning_by_email_already_linked():
    from app.services.sso_service import resolve_sso_user

    db = _mock_db()
    email_user = MagicMock(id=uuid.uuid4(), google_id="gid-1")
    db.execute = AsyncMock(side_effect=[
        _FakeResult(scalar_one_or_none=None),
        _FakeResult(scalar_one_or_none=email_user),
    ])

    result = asyncio.run(resolve_sso_user(
        db, "google_id", "gid-1", "user@example.com", "Jane", None, "", "google",
    ))
    assert result is email_user


def test_resolve_sso_user_returning_by_email_linked_to_different_provider_id_raises():
    from app.services.sso_service import resolve_sso_user, ProviderError

    db = _mock_db()
    email_user = MagicMock(id=uuid.uuid4(), google_id="other-gid")
    db.execute = AsyncMock(side_effect=[
        _FakeResult(scalar_one_or_none=None),
        _FakeResult(scalar_one_or_none=email_user),
    ])

    with pytest.raises(ProviderError):
        asyncio.run(resolve_sso_user(
            db, "google_id", "gid-1", "user@example.com", "Jane", None, "", "google",
        ))


def test_resolve_sso_user_links_existing_unlinked_user():
    from app.services.sso_service import resolve_sso_user

    db = _mock_db()
    email_user = MagicMock(id=uuid.uuid4(), google_id=None, avatar_url=None, is_verified=False)
    db.execute = AsyncMock(side_effect=[
        _FakeResult(scalar_one_or_none=None),
        _FakeResult(scalar_one_or_none=email_user),
    ])

    result = asyncio.run(resolve_sso_user(
        db, "google_id", "gid-1", "user@example.com", "Jane", "http://pic", "", "google",
    ))

    assert result is email_user
    assert email_user.google_id == "gid-1"
    assert email_user.oauth_provider == "google"
    assert email_user.avatar_url == "http://pic"
    assert email_user.is_verified is True


def test_resolve_sso_user_new_user_requires_invite_id():
    from app.services.sso_service import resolve_sso_user, SignupInviteRequiredError

    db = _mock_db()
    db.execute = AsyncMock(side_effect=[
        _FakeResult(scalar_one_or_none=None),
        _FakeResult(scalar_one_or_none=None),
    ])

    with pytest.raises(SignupInviteRequiredError):
        asyncio.run(resolve_sso_user(
            db, "google_id", "gid-1", "user@example.com", "Jane", None, "", "google",
        ))


def test_resolve_sso_user_new_user_bad_invite_uuid_raises_not_found():
    from app.services.sso_service import resolve_sso_user, InvitationNotFoundError

    db = _mock_db()
    db.execute = AsyncMock(side_effect=[
        _FakeResult(scalar_one_or_none=None),
        _FakeResult(scalar_one_or_none=None),
    ])

    with pytest.raises(InvitationNotFoundError):
        asyncio.run(resolve_sso_user(
            db, "google_id", "gid-1", "user@example.com", "Jane", None, "not-a-uuid", "google",
        ))


def test_resolve_sso_user_new_user_invitation_not_found():
    from app.services.sso_service import resolve_sso_user, InvitationNotFoundError

    db = _mock_db()
    invite_id = str(uuid.uuid4())
    db.execute = AsyncMock(side_effect=[
        _FakeResult(scalar_one_or_none=None),
        _FakeResult(scalar_one_or_none=None),
        _FakeResult(scalar_one_or_none=None),
    ])

    with pytest.raises(InvitationNotFoundError):
        asyncio.run(resolve_sso_user(
            db, "google_id", "gid-1", "user@example.com", "Jane", None, invite_id, "google",
        ))


def test_resolve_sso_user_new_user_invitation_invalid():
    from app.services.sso_service import resolve_sso_user, InvitationInvalidError

    db = _mock_db()
    invite_id = str(uuid.uuid4())
    invitation = MagicMock(is_valid=False)
    db.execute = AsyncMock(side_effect=[
        _FakeResult(scalar_one_or_none=None),
        _FakeResult(scalar_one_or_none=None),
        _FakeResult(scalar_one_or_none=invitation),
    ])

    with pytest.raises(InvitationInvalidError):
        asyncio.run(resolve_sso_user(
            db, "google_id", "gid-1", "user@example.com", "Jane", None, invite_id, "google",
        ))


def test_resolve_sso_user_new_user_email_mismatch():
    from app.services.sso_service import resolve_sso_user, EmailMismatchError

    db = _mock_db()
    invite_id = str(uuid.uuid4())
    invitation = MagicMock(is_valid=True, email="other@example.com")
    db.execute = AsyncMock(side_effect=[
        _FakeResult(scalar_one_or_none=None),
        _FakeResult(scalar_one_or_none=None),
        _FakeResult(scalar_one_or_none=invitation),
    ])

    with pytest.raises(EmailMismatchError):
        asyncio.run(resolve_sso_user(
            db, "google_id", "gid-1", "user@example.com", "Jane", None, invite_id, "google",
        ))


def test_resolve_sso_user_new_user_created_and_default_workspace_created():
    from app.services.sso_service import resolve_sso_user

    db = _mock_db()
    invite_id = str(uuid.uuid4())
    company_id = uuid.uuid4()
    invitation = MagicMock(is_valid=True, email="user@example.com", company_id=company_id, role="member")
    fake_company = MagicMock(id=company_id, name="Acme")
    db.execute = AsyncMock(side_effect=[
        _FakeResult(scalar_one_or_none=None),  # provider lookup
        _FakeResult(scalar_one_or_none=None),  # email lookup
        _FakeResult(scalar_one_or_none=invitation),  # invitation lookup
        _FakeResult(scalar_one_or_none=fake_company),  # company lookup (workspace helper)
        _FakeResult(scalar_one_or_none=None),  # existing workspace lookup
    ])

    result = asyncio.run(resolve_sso_user(
        db, "google_id", "gid-1", "user@example.com", "Jane", None, invite_id, "google",
    ))

    assert result.email_id == "user@example.com"
    assert result.company_id == company_id
    invitation.mark_as_used.assert_called_once()
    assert db.add.call_count == 2  # new user + default workspace


# ---------------------------------------------------------------------------
# issue_tokens_for_user
# ---------------------------------------------------------------------------

def test_issue_tokens_for_user_success():
    from app.services.sso_service import issue_tokens_for_user

    db = _mock_db()
    user = MagicMock(
        id=uuid.uuid4(), email_id="user@example.com", role="member",
        company_id=uuid.uuid4(), is_active=True, avatar_url=None,
    )
    user.name = "Jane"
    fake_company = MagicMock(is_active=True)
    fake_company.name = "Acme"
    fake_workspace = MagicMock(id=uuid.uuid4())
    db.execute = AsyncMock(side_effect=[
        _FakeResult(scalar_one_or_none=fake_company),
        _FakeResult(scalar_one_or_none=fake_workspace),
    ])

    with patch(f"{MODPATH}.tokens.settings") as mock_settings, \
         patch(f"{MODPATH}.tokens.create_token_data", return_value={"sub": "x"}) as mock_ctd, \
         patch(f"{MODPATH}.tokens.create_access_token", return_value="access-tok") as mock_at, \
         patch(f"{MODPATH}.tokens.create_refresh_token", return_value="refresh-tok") as mock_rt:
        mock_settings.ACCESS_TOKEN_EXPIRE_MINUTES = 30

        result = asyncio.run(issue_tokens_for_user(db, user))

    assert result.access_token == "access-tok"
    assert result.refresh_token == "refresh-tok"
    assert result.expires_in == 1800
    assert result.company_name == "Acme"
    assert result.default_workspace_id == str(fake_workspace.id)


def test_issue_tokens_for_user_inactive_user_raises():
    from app.services.sso_service import issue_tokens_for_user, ProviderError

    db = _mock_db()
    user = MagicMock(is_active=False, company_id=uuid.uuid4())
    db.execute = AsyncMock(return_value=_FakeResult(scalar_one_or_none=None))

    with pytest.raises(ProviderError):
        asyncio.run(issue_tokens_for_user(db, user))


def test_issue_tokens_for_user_inactive_company_raises():
    from app.services.sso_service import issue_tokens_for_user, ProviderError

    db = _mock_db()
    user = MagicMock(is_active=True, company_id=uuid.uuid4())
    fake_company = MagicMock(is_active=False)
    db.execute = AsyncMock(return_value=_FakeResult(scalar_one_or_none=fake_company))

    with pytest.raises(ProviderError):
        asyncio.run(issue_tokens_for_user(db, user))
