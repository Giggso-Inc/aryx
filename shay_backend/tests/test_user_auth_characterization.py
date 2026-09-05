"""
Golden-master / characterization tests for app/routes/user_auth.py.

Purpose: this file (1,870 lines, 14 endpoints) is about to be split into a
routes package (see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5,
item 2 — same methodology already proven on app/routes/datasources.py).
Before the split, we capture the CURRENT observable behavior of every
endpoint that previously had zero test coverage, so the split can be
verified to change nothing.

Coverage already exists elsewhere and is NOT duplicated here:
- tests/test_user_auth_reset.py: reset_password, forgot_password.
- tests/test_user_auth_reinvite.py: bulk_invite_users (inactive-user
  reactivation), register_user (invite-based reactivation),
  decrypt_registration_invite.

This file covers the endpoints those two files do not touch: invite_user,
login_user, request_set_password, confirm_set_password,
get_current_user_profile_details, upload_profile_image,
remove_profile_photo, update_current_user_personal_info,
update_current_user_password.

These are characterization tests, not "correctness" tests: assertions match
what the code actually does today, bugs included (see inline notes, e.g.
login_user's debug print() calls and its 500-on-verify-exception path).

Pattern follows tests/test_datasources_characterization.py:
- FastAPI TestClient with `app.include_router(router, prefix=...)`.
- `app.dependency_overrides[get_db] = lambda: mock_db`.
- MagicMock/AsyncMock for services; no real DB, no real HTTP.
- `_run()` + asyncio.run() instead of pytest-asyncio (no async plugin
  installed in this suite).

Do not modify app/routes/user_auth.py (or the post-split package) from
this file's tests.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _scalar_result(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _make_client(mock_db, with_user_state=None):
    """Build a TestClient wired to the user_auth router.

    If `with_user_state` is given, a tiny middleware sets
    `request.state.user_id` before the request reaches the endpoint — this
    stands in for the real `AuthMiddleware`, which is not mounted in these
    tests, and is required by the two endpoints
    (`update_current_user_personal_info`, `update_current_user_password`)
    that read `request.state.user_id` directly instead of via a dependency.
    """
    from app.core.database import get_db
    from app.routes.user_auth import router

    app = FastAPI()

    if with_user_state is not None:
        @app.middleware("http")
        async def _inject_user_id(request, call_next):
            request.state.user_id = with_user_state
            return await call_next(request)

    app.include_router(router, prefix="/api/v1/user-auth")
    app.dependency_overrides[get_db] = lambda: mock_db
    return TestClient(app, raise_server_exceptions=False)


# ===========================================================================
# POST /invite — invite_user
# ===========================================================================

class TestInviteUser:
    def _payload(self, **overrides):
        payload = {
            "email": "newperson@example.com",
            "company_id": str(uuid.uuid4()),
            "role": "user",
            "platform_name": "Aryx",
        }
        payload.update(overrides)
        return payload

    @pytest.mark.unit
    def test_company_not_found_returns_404(self, mock_db):
        mock_db.execute = AsyncMock(return_value=_scalar_result(None))
        client = _make_client(mock_db)

        resp = client.post(
            "/api/v1/user-auth/invite",
            json=self._payload(),
        )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Company not found"

    @pytest.mark.unit
    def test_existing_active_user_returns_409(self, mock_db, mock_company):
        existing_user = MagicMock()
        existing_user.is_active = True
        mock_db.execute = AsyncMock(
            side_effect=[
                _scalar_result(mock_company),
                _scalar_result(existing_user),
            ]
        )
        client = _make_client(mock_db)

        resp = client.post(
            "/api/v1/user-auth/invite",
            json=self._payload(),
        )
        assert resp.status_code == 409
        assert "already exists" in resp.json()["detail"]

    @pytest.mark.unit
    def test_happy_path_sends_default_email(self, mock_db, mock_company):
        mock_db.execute = AsyncMock(
            side_effect=[
                _scalar_result(mock_company),  # company lookup
                _scalar_result(None),          # existing user lookup
                _scalar_result(None),          # existing invitation lookup
            ]
        )
        client = _make_client(mock_db)

        with patch("app.routes.user_auth.invitations.link_shortener_service.shorten",
                   new=AsyncMock(return_value="short-link")), \
             patch("app.routes.user_auth.invitations.email_service.send_invitation_email",
                   return_value=True):
            resp = client.post(
                "/api/v1/user-auth/invite",
                json=self._payload(),
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["email_id"] == "newperson@example.com"
        assert body["registration_link"] == "short-link"
        assert "Email sent" in body["message"]
        mock_db.commit.assert_awaited()


# ===========================================================================
# POST /login — login_user
# ===========================================================================

class TestLoginUser:
    def _payload(self, **overrides):
        payload = {
            "email_id": "user@example.com",
            "password": "ValidPass123!",
            "encrypted": False,
        }
        payload.update(overrides)
        return payload

    @pytest.mark.unit
    def test_unknown_email_returns_404_with_error_code(self, mock_db):
        mock_db.execute = AsyncMock(return_value=_scalar_result(None))
        client = _make_client(mock_db)

        resp = client.post("/api/v1/user-auth/login", json=self._payload())
        assert resp.status_code == 404
        assert resp.json()["detail"]["error_code"] == "E004"

    @pytest.mark.unit
    def test_inactive_user_returns_403_with_error_code(self, mock_db):
        user = MagicMock()
        user.is_active = False
        mock_db.execute = AsyncMock(return_value=_scalar_result(user))
        client = _make_client(mock_db)

        resp = client.post("/api/v1/user-auth/login", json=self._payload())
        assert resp.status_code == 403
        assert resp.json()["detail"]["error_code"] == "E005"

    @pytest.mark.unit
    def test_sso_only_user_returns_401_with_error_code(self, mock_db):
        user = MagicMock()
        user.is_active = True
        user.password_hash = None
        user.oauth_provider = "google"
        mock_db.execute = AsyncMock(return_value=_scalar_result(user))
        client = _make_client(mock_db)

        resp = client.post("/api/v1/user-auth/login", json=self._payload())
        assert resp.status_code == 401
        assert resp.json()["detail"]["error_code"] == "E007"
        assert resp.json()["detail"]["oauth_provider"] == "google"

    @pytest.mark.unit
    def test_wrong_password_returns_401(self, mock_db):
        user = MagicMock()
        user.is_active = True
        user.password_hash = "hashed"
        mock_db.execute = AsyncMock(return_value=_scalar_result(user))
        client = _make_client(mock_db)

        with patch("app.routes.user_auth._login_helpers.verify_password", return_value=False):
            resp = client.post("/api/v1/user-auth/login", json=self._payload())
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid password"

    @pytest.mark.unit
    def test_password_verification_exception_returns_500(self, mock_db):
        """Current behavior: any exception raised by verify_password() is
        caught and re-raised as a 500 with the exception text embedded in
        the detail message, rather than propagating or mapping to 401."""
        user = MagicMock()
        user.is_active = True
        user.password_hash = "hashed"
        mock_db.execute = AsyncMock(return_value=_scalar_result(user))
        client = _make_client(mock_db)

        with patch("app.routes.user_auth._login_helpers.verify_password",
                   side_effect=RuntimeError("boom")):
            resp = client.post("/api/v1/user-auth/login", json=self._payload())
        assert resp.status_code == 500
        assert "boom" in resp.json()["detail"]

    @pytest.mark.unit
    def test_happy_path_returns_tokens_and_creates_default_workspace(self, mock_db):
        user = MagicMock()
        user.id = "user-001"
        user.is_active = True
        user.password_hash = "hashed"
        user.email_id = "user@example.com"
        user.role = "user"
        user.company_id = "company-001"
        user.name = "Some User"
        user.avatar_url = None

        company = MagicMock()
        company.id = "company-001"
        company.name = "Test Co"
        company.is_active = True

        mock_db.execute = AsyncMock(
            side_effect=[
                _scalar_result(user),      # user lookup
                _scalar_result(company),   # company lookup
                _scalar_result(None),      # no existing default workspace
            ]
        )
        client = _make_client(mock_db)

        with patch("app.routes.user_auth._login_helpers.verify_password", return_value=True), \
             patch("app.routes.user_auth.login.ensure_workspace_membership", new=AsyncMock()), \
             patch("app.routes.user_auth.login.create_access_token", return_value="access-token"), \
             patch("app.routes.user_auth.login.create_refresh_token", return_value="refresh-token"):
            resp = client.post("/api/v1/user-auth/login", json=self._payload())

        assert resp.status_code == 200
        body = resp.json()
        assert body["access_token"] == "access-token"
        assert body["refresh_token"] == "refresh-token"
        assert body["user_id"] == "user-001"
        assert body["company_name"] == "Test Co"
        assert user.last_login is not None


# ===========================================================================
# POST /set-password/request — request_set_password
# ===========================================================================

class TestRequestSetPassword:
    @pytest.mark.unit
    def test_unknown_email_returns_generic_message_no_enumeration(self, mock_db):
        mock_db.execute = AsyncMock(return_value=_scalar_result(None))
        client = _make_client(mock_db)

        resp = client.post(
            "/api/v1/user-auth/set-password/request",
            json={"email_id": "nobody@example.com"},
        )
        assert resp.status_code == 200
        assert "If this email exists" in resp.json()["message"]
        mock_db.commit.assert_not_awaited()

    @pytest.mark.unit
    def test_password_holding_user_gets_same_generic_message_and_no_email(self, mock_db):
        """Never reveal whether the account is SSO-only: a user WITH a
        password hash gets the identical response as an unknown email, and
        no email is sent."""
        user = MagicMock()
        user.password_hash = "already-has-a-password"
        mock_db.execute = AsyncMock(return_value=_scalar_result(user))
        client = _make_client(mock_db)

        with patch("app.routes.user_auth.sso_password.email_service.send_password_reset_email") as mock_send:
            resp = client.post(
                "/api/v1/user-auth/set-password/request",
                json={"email_id": "user@example.com"},
            )
        assert resp.status_code == 200
        assert "If this email exists" in resp.json()["message"]
        mock_send.assert_not_called()
        mock_db.commit.assert_not_awaited()

    @pytest.mark.unit
    def test_sso_only_user_gets_token_and_email(self, mock_db):
        user = MagicMock()
        user.password_hash = None
        user.email_id = "sso@example.com"
        user.company_id = "company-001"
        user.id = "user-001"
        user.name = "SSO User"
        mock_db.execute = AsyncMock(return_value=_scalar_result(user))
        client = _make_client(mock_db)

        fake_token = MagicMock()
        fake_token.token = "abc123"
        with patch("app.models.email_verification_token.EmailVerificationToken.create_token",
                   return_value=fake_token), \
             patch("app.routes.user_auth.sso_password.email_service.send_password_reset_email") as mock_send:
            resp = client.post(
                "/api/v1/user-auth/set-password/request",
                json={"email_id": "sso@example.com"},
            )
        assert resp.status_code == 200
        mock_send.assert_called_once()
        mock_db.commit.assert_awaited_once()


# ===========================================================================
# POST /set-password/confirm — confirm_set_password
# ===========================================================================

class TestConfirmSetPassword:
    def _payload(self, **overrides):
        payload = {
            "token": "good-token",
            "user_id": "user-001",
            "new_password": "ValidPass123!",
            "confirm_password": "ValidPass123!",
            "encrypted": False,
        }
        payload.update(overrides)
        return payload

    @pytest.mark.unit
    def test_unknown_token_returns_400(self, mock_db):
        mock_db.execute = AsyncMock(return_value=_scalar_result(None))
        client = _make_client(mock_db)

        resp = client.post("/api/v1/user-auth/set-password/confirm", json=self._payload())
        assert resp.status_code == 400
        assert resp.json()["detail"]["error_code"] == "SET_PWD_001"

    @pytest.mark.unit
    def test_mismatched_passwords_rejected_by_schema_not_endpoint_code(self, mock_db):
        """Current behavior: SetPasswordConfirmRequest.confirm_password already
        has a pydantic validator that checks it against new_password, so a
        mismatch is rejected with 422 by FastAPI's own request validation
        before the endpoint even runs — the endpoint's own
        `if new_password_to_use != confirm_password_to_use` check (which
        only matters after decryption, when encrypted=True) is unreachable
        for plaintext mismatches."""
        client = _make_client(mock_db)

        resp = client.post(
            "/api/v1/user-auth/set-password/confirm",
            json=self._payload(confirm_password="Different123!"),
        )
        assert resp.status_code == 422

    @pytest.mark.unit
    def test_happy_path_sets_password_and_marks_token_used(self, mock_db):
        token_record = MagicMock()
        token_record.is_valid = True
        token_record.token_type = "set_password"
        token_record.user_id = "user-001"

        user = MagicMock()
        user.oauth_provider = "google"
        mock_db.execute = AsyncMock(
            side_effect=[
                _scalar_result(token_record),
                _scalar_result(user),
            ]
        )
        client = _make_client(mock_db)

        with patch("app.routes.user_auth.sso_password.get_password_hash", return_value="new-hash"):
            resp = client.post("/api/v1/user-auth/set-password/confirm", json=self._payload())

        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert user.password_hash == "new-hash"
        token_record.mark_as_used.assert_called_once()
        mock_db.commit.assert_awaited_once()


# ===========================================================================
# GET /profile — get_current_user_profile_details
# ===========================================================================

class TestGetCurrentUserProfileDetails:
    @pytest.mark.unit
    def test_happy_path_returns_profile_dict(self, mock_db, admin_user):
        admin_user.is_verified = True
        admin_user.preferences = {"theme": "dark"}
        admin_user.last_login = None
        admin_user.created_datetime = None
        admin_user.updated_datetime = None
        admin_user.oauth_provider = "local"

        client = _make_client(mock_db)
        with patch("app.routes.user_auth.profile.get_current_user_required",
                   new=AsyncMock(return_value=admin_user)):
            resp = client.get(
                "/api/v1/user-auth/profile",
                headers={"Authorization": "Bearer test-token"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == str(admin_user.id)
        assert body["email_id"] == admin_user.email_id
        assert body["preferences"] == {"theme": "dark"}


# ===========================================================================
# POST /profile/upload-image — upload_profile_image
# ===========================================================================

class TestUploadProfileImage:
    @pytest.mark.unit
    def test_invalid_extension_returns_400(self, mock_db, admin_user):
        client = _make_client(mock_db)
        with patch("app.routes.user_auth.profile.get_current_user_required",
                   new=AsyncMock(return_value=admin_user)):
            resp = client.post(
                "/api/v1/user-auth/profile/upload-image",
                files={"file": ("notes.txt", b"hello", "text/plain")},
                headers={"Authorization": "Bearer test-token"},
            )
        assert resp.status_code == 400
        assert "Invalid file type" in resp.json()["detail"]

    @pytest.mark.unit
    def test_happy_path_returns_avatar_url(self, mock_db, admin_user):
        storage_service = MagicMock()
        storage_service.upload_file = AsyncMock(
            return_value={"file_url": "https://storage.example.com/avatar.png"}
        )
        client = _make_client(mock_db)
        with patch("app.routes.user_auth.profile.get_current_user_required",
                   new=AsyncMock(return_value=admin_user)), \
             patch("app.routes.user_auth.profile.get_file_storage_service",
                   return_value=storage_service):
            resp = client.post(
                "/api/v1/user-auth/profile/upload-image",
                files={"file": ("avatar.png", b"\x89PNG\r\n", "image/png")},
                headers={"Authorization": "Bearer test-token"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["avatar_url"] == "https://storage.example.com/avatar.png"
        assert "successfully" in body["message"]


# ===========================================================================
# DELETE /profile/photo — remove_profile_photo
# ===========================================================================

class TestRemoveProfilePhoto:
    @pytest.mark.unit
    def test_user_row_not_found_returns_404(self, mock_db, admin_user):
        mock_db.execute = AsyncMock(return_value=_scalar_result(None))
        client = _make_client(mock_db)
        with patch("app.routes.user_auth.profile.get_current_user_required",
                   new=AsyncMock(return_value=admin_user)):
            resp = client.delete(
                "/api/v1/user-auth/profile/photo",
                headers={"Authorization": "Bearer test-token"},
            )
        assert resp.status_code == 404

    @pytest.mark.unit
    def test_happy_path_clears_avatar_url(self, mock_db, admin_user):
        user_row = MagicMock()
        user_row.avatar_url = "https://old-avatar.png"
        mock_db.execute = AsyncMock(return_value=_scalar_result(user_row))
        client = _make_client(mock_db)
        with patch("app.routes.user_auth.profile.get_current_user_required",
                   new=AsyncMock(return_value=admin_user)):
            resp = client.delete(
                "/api/v1/user-auth/profile/photo",
                headers={"Authorization": "Bearer test-token"},
            )
        assert resp.status_code == 200
        assert resp.json()["message"] == "Profile photo removed successfully"
        assert user_row.avatar_url is None
        mock_db.commit.assert_awaited_once()


# ===========================================================================
# PUT /profile — update_current_user_personal_info
# ===========================================================================

class TestUpdateCurrentUserPersonalInfo:
    @pytest.mark.unit
    def test_missing_user_id_in_request_state_returns_401(self, mock_db):
        client = _make_client(mock_db)  # no with_user_state -> getattr returns None
        resp = client.put(
            "/api/v1/user-auth/profile",
            json={"name": "New Name"},
        )
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Authentication required"

    @pytest.mark.unit
    def test_user_not_found_returns_404(self, mock_db):
        mock_db.execute = AsyncMock(return_value=_scalar_result(None))
        client = _make_client(mock_db, with_user_state="user-001")
        resp = client.put(
            "/api/v1/user-auth/profile",
            json={"name": "New Name"},
        )
        assert resp.status_code == 404

    @pytest.mark.unit
    def test_happy_path_updates_allowed_fields(self, mock_db):
        user = MagicMock()
        user.id = "user-001"
        user.email_id = "user@example.com"
        user.role = "user"
        user.is_active = True
        user.is_verified = True
        user.oauth_provider = "local"
        user.last_login = None
        user.created_datetime = None
        user.updated_datetime = None
        mock_db.execute = AsyncMock(return_value=_scalar_result(user))
        client = _make_client(mock_db, with_user_state="user-001")

        resp = client.put(
            "/api/v1/user-auth/profile",
            json={"name": "New Name", "preferences": {"theme": "dark"}},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert sorted(body["updated_fields"]) == ["name", "preferences"]
        assert user.name == "New Name"
        assert user.preferences == {"theme": "dark"}
        mock_db.commit.assert_awaited_once()

    @pytest.mark.unit
    def test_field_not_on_schema_is_silently_ignored(self, mock_db):
        """Current behavior: `role` isn't declared on ProfileUpdateRequest,
        and the schema does not forbid extra fields, so pydantic silently
        drops it — the request succeeds with an empty updated_fields list
        rather than hitting the endpoint's own
        'is not allowed for personal information updates' 400 branch (that
        branch is reachable only for a field pydantic *does* know about
        but the endpoint's own allow-list does not)."""
        user = MagicMock()
        user.id = "user-001"
        user.email_id = "user@example.com"
        user.role = "user"
        user.is_active = True
        user.is_verified = True
        user.oauth_provider = "local"
        user.last_login = None
        user.created_datetime = None
        user.updated_datetime = None
        mock_db.execute = AsyncMock(return_value=_scalar_result(user))
        client = _make_client(mock_db, with_user_state="user-001")

        resp = client.put(
            "/api/v1/user-auth/profile",
            json={"role": "admin"},
        )
        assert resp.status_code == 200
        assert resp.json()["updated_fields"] == []
        mock_db.commit.assert_not_awaited()


# ===========================================================================
# PUT /password — update_current_user_password
# ===========================================================================

class TestUpdateCurrentUserPassword:
    def _payload(self, **overrides):
        payload = {
            "confirm_old_password": "OldPass123!",
            "new_password": "NewPass456!",
            "confirm_new_password": "NewPass456!",
            "encrypted": False,
        }
        payload.update(overrides)
        return payload

    @pytest.mark.unit
    def test_missing_user_id_in_request_state_returns_401(self, mock_db):
        client = _make_client(mock_db)
        resp = client.put("/api/v1/user-auth/password", json=self._payload())
        assert resp.status_code == 401

    @pytest.mark.unit
    def test_wrong_old_password_returns_400(self, mock_db):
        user = MagicMock()
        user.password_hash = "stored-hash"
        mock_db.execute = AsyncMock(return_value=_scalar_result(user))
        client = _make_client(mock_db, with_user_state="user-001")

        with patch("app.routes.user_auth.update_password.verify_password", return_value=False):
            resp = client.put("/api/v1/user-auth/password", json=self._payload())
        assert resp.status_code == 400
        assert resp.json()["detail"] == "Current password is incorrect"

    @pytest.mark.unit
    def test_new_password_same_as_old_returns_400(self, mock_db):
        user = MagicMock()
        user.password_hash = "stored-hash"
        mock_db.execute = AsyncMock(return_value=_scalar_result(user))
        client = _make_client(mock_db, with_user_state="user-001")

        with patch("app.routes.user_auth.update_password.verify_password", return_value=True):
            resp = client.put(
                "/api/v1/user-auth/password",
                json=self._payload(
                    confirm_old_password="SamePass123!",
                    new_password="SamePass123!",
                    confirm_new_password="SamePass123!",
                ),
            )
        assert resp.status_code == 400
        assert "different from current password" in resp.json()["detail"]

    @pytest.mark.unit
    def test_happy_path_updates_password_hash(self, mock_db):
        user = MagicMock()
        user.password_hash = "stored-hash"
        mock_db.execute = AsyncMock(return_value=_scalar_result(user))
        client = _make_client(mock_db, with_user_state="user-001")

        with patch("app.routes.user_auth.update_password.verify_password", return_value=True), \
             patch("app.routes.user_auth.update_password.get_password_hash", return_value="new-hash"):
            resp = client.put("/api/v1/user-auth/password", json=self._payload())

        assert resp.status_code == 200
        assert resp.json()["message"] == "Password updated successfully"
        assert user.password_hash == "new-hash"
        mock_db.commit.assert_awaited_once()
