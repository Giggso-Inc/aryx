"""
Golden-master / characterization tests for app/services/email_verification_service.py.

Purpose: this file had ZERO dedicated full-file test coverage before this pass
(tests/test_email_verification_url_safe.py covers only the URL-safe-token and
support_email slices of send_verification_email, not the other five public
methods). It is about to be split into a package (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Before the split, we capture
the CURRENT observable behavior of every public method so the split can be
verified to change nothing.

These are characterization tests, not "correctness" tests: assertions match
what the code actually does today, bugs included.

Pattern follows tests/test_channels_characterization.py: no real DB, mock_db
AsyncMock, `asyncio.run()` instead of pytest-asyncio (no async plugin
installed), and `unittest.mock.patch` at the exact import path used inside
the module under test.

Do not modify app/services/email_verification_service.py from this file's
tests.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException


MODPATH = "app.services.email_verification_service"


def _svc():
    from app.services.email_verification_service import EmailVerificationService
    return EmailVerificationService()


def _mock_db():
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


class _FakeResult:
    def __init__(self, scalar_one_or_none=None, all_=None):
        self._son = scalar_one_or_none
        self._all = all_ if all_ is not None else []

    def scalar_one_or_none(self):
        return self._son

    def scalars(self):
        m = MagicMock()
        m.all = MagicMock(return_value=self._all)
        return m


# ---------------------------------------------------------------------------
# _resolve_platform_url
# ---------------------------------------------------------------------------

def test_resolve_platform_url_empty_uses_fallback():
    from app.services.email_verification_service import _resolve_platform_url
    with patch(f"{MODPATH}.send.settings") as mock_settings:
        mock_settings.FRONTEND_URL = "https://front.example.com"
        mock_settings.PLATFORM_URL = "https://platform.example.com"
        assert _resolve_platform_url(None) == "https://front.example.com"
        assert _resolve_platform_url("") == "https://front.example.com"


def test_resolve_platform_url_absolute_passthrough():
    from app.services.email_verification_service import _resolve_platform_url
    with patch(f"{MODPATH}.send.settings") as mock_settings:
        mock_settings.FRONTEND_URL = "https://front.example.com"
        mock_settings.PLATFORM_URL = "https://platform.example.com"
        assert _resolve_platform_url("https://custom.example.com/") == "https://custom.example.com"


def test_resolve_platform_url_relative_root_returns_fallback():
    from app.services.email_verification_service import _resolve_platform_url
    with patch(f"{MODPATH}.send.settings") as mock_settings:
        mock_settings.FRONTEND_URL = "https://front.example.com"
        mock_settings.PLATFORM_URL = "https://platform.example.com"
        assert _resolve_platform_url("/") == "https://front.example.com"


def test_resolve_platform_url_relative_path_appends_to_fallback():
    from app.services.email_verification_service import _resolve_platform_url
    with patch(f"{MODPATH}.send.settings") as mock_settings:
        mock_settings.FRONTEND_URL = "https://front.example.com"
        mock_settings.PLATFORM_URL = "https://platform.example.com"
        assert _resolve_platform_url("/some/path/") == "https://front.example.com/some/path"


def test_resolve_platform_url_no_frontend_falls_back_to_platform_url_default():
    from app.services.email_verification_service import _resolve_platform_url
    with patch(f"{MODPATH}.send.settings") as mock_settings:
        mock_settings.FRONTEND_URL = None
        mock_settings.PLATFORM_URL = None
        assert _resolve_platform_url(None) == "http://localhost:3000"


# ---------------------------------------------------------------------------
# generate_verification_token
# ---------------------------------------------------------------------------

def test_generate_verification_token_invalidates_then_creates():
    svc = _svc()
    db = _mock_db()
    db.execute = AsyncMock(return_value=_FakeResult(all_=[]))

    result = asyncio.run(svc.generate_verification_token(
        email="user@example.com",
        company_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        db=db,
    ))

    assert result.email == "user@example.com"
    assert result.token_type == "company_signup"
    db.add.assert_called_once()
    db.flush.assert_awaited()


def test_generate_verification_token_custom_type():
    svc = _svc()
    db = _mock_db()
    db.execute = AsyncMock(return_value=_FakeResult(all_=[]))

    result = asyncio.run(svc.generate_verification_token(
        email="user@example.com",
        company_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        token_type="password_reset",
        db=db,
    ))
    assert result.token_type == "password_reset"


# ---------------------------------------------------------------------------
# send_verification_email
# ---------------------------------------------------------------------------

def test_send_verification_email_success():
    svc = _svc()
    with patch(f"{MODPATH}.send.settings") as mock_settings, \
         patch(f"{MODPATH}.send.email_service") as mock_email_svc, \
         patch(f"{MODPATH}.send.link_shortener_service") as mock_shortener:
        mock_settings.FRONTEND_URL = "https://app.example.com"
        mock_settings.PLATFORM_URL = "https://app.example.com"
        mock_settings.PLATFORM_NAME = "Accsell"
        mock_settings.SUPPORT_EMAIL = "support@accsell.io"
        mock_settings.EMAIL_VERIFICATION_EXPIRY_HOURS = 24
        mock_email_svc.send_verification_email = MagicMock(return_value=True)
        mock_shortener.shorten = AsyncMock(return_value="https://short.link/xyz")

        result = asyncio.run(svc.send_verification_email(
            email="user@example.com",
            token="tok-abc",
            company_name="Acme Corp",
        ))

    assert result is True


def test_send_verification_email_uses_email_local_part_when_no_user_name():
    svc = _svc()
    captured = {}
    with patch(f"{MODPATH}.send.settings") as mock_settings, \
         patch(f"{MODPATH}.send.email_service") as mock_email_svc, \
         patch(f"{MODPATH}.send.link_shortener_service") as mock_shortener:
        mock_settings.FRONTEND_URL = "https://app.example.com"
        mock_settings.PLATFORM_URL = "https://app.example.com"
        mock_settings.PLATFORM_NAME = "Accsell"
        mock_settings.SUPPORT_EMAIL = "support@accsell.io"
        mock_settings.EMAIL_VERIFICATION_EXPIRY_HOURS = 24

        def _send(to_email, verification_data, platform_url):
            captured.update(verification_data)
            return True

        mock_email_svc.send_verification_email = _send
        mock_shortener.shorten = AsyncMock(return_value="https://short.link/xyz")

        asyncio.run(svc.send_verification_email(
            email="jdoe@example.com",
            token="tok-abc",
            company_name="Acme Corp",
        ))

    assert captured["user_name"] == "jdoe"


def test_send_verification_email_exception_returns_false():
    svc = _svc()
    with patch(f"{MODPATH}.send.settings") as mock_settings, \
         patch(f"{MODPATH}.send.email_service") as mock_email_svc, \
         patch(f"{MODPATH}.send.link_shortener_service") as mock_shortener:
        mock_settings.FRONTEND_URL = "https://app.example.com"
        mock_settings.PLATFORM_URL = "https://app.example.com"
        mock_settings.PLATFORM_NAME = "Accsell"
        mock_settings.SUPPORT_EMAIL = "support@accsell.io"
        mock_settings.EMAIL_VERIFICATION_EXPIRY_HOURS = 24
        mock_email_svc.send_verification_email = MagicMock(side_effect=RuntimeError("smtp down"))
        mock_shortener.shorten = AsyncMock(return_value="https://short.link/xyz")

        result = asyncio.run(svc.send_verification_email(
            email="user@example.com",
            token="tok-abc",
            company_name="Acme Corp",
        ))

    assert result is False


# ---------------------------------------------------------------------------
# verify_token
# ---------------------------------------------------------------------------

def test_verify_token_invalid_token_raises_400():
    svc = _svc()
    db = _mock_db()
    db.execute = AsyncMock(return_value=_FakeResult(scalar_one_or_none=None))

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(svc.verify_token("bad-token", db))
    assert exc_info.value.status_code == 400
    assert "Invalid verification token" in exc_info.value.detail


def test_verify_token_already_used_raises_400():
    svc = _svc()
    db = _mock_db()
    fake_token = MagicMock(is_used=True, is_expired=False)
    db.execute = AsyncMock(return_value=_FakeResult(scalar_one_or_none=fake_token))

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(svc.verify_token("used-token", db))
    assert exc_info.value.status_code == 400
    assert "already been used" in exc_info.value.detail


def test_verify_token_expired_raises_400():
    svc = _svc()
    db = _mock_db()
    fake_token = MagicMock(is_used=False, is_expired=True)
    db.execute = AsyncMock(return_value=_FakeResult(scalar_one_or_none=fake_token))

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(svc.verify_token("expired-token", db))
    assert exc_info.value.status_code == 400
    assert "expired" in exc_info.value.detail


def test_verify_token_user_not_found_raises_404():
    svc = _svc()
    db = _mock_db()
    fake_token = MagicMock(is_used=False, is_expired=False, user_id=uuid.uuid4(), company_id=uuid.uuid4())
    db.execute = AsyncMock(side_effect=[
        _FakeResult(scalar_one_or_none=fake_token),
        _FakeResult(scalar_one_or_none=None),
    ])

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(svc.verify_token("tok", db))
    assert exc_info.value.status_code == 404
    assert "User not found" in exc_info.value.detail


def test_verify_token_company_not_found_raises_404():
    svc = _svc()
    db = _mock_db()
    fake_token = MagicMock(is_used=False, is_expired=False, user_id=uuid.uuid4(), company_id=uuid.uuid4())
    fake_user = MagicMock()
    db.execute = AsyncMock(side_effect=[
        _FakeResult(scalar_one_or_none=fake_token),
        _FakeResult(scalar_one_or_none=fake_user),
        _FakeResult(scalar_one_or_none=None),
    ])

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(svc.verify_token("tok", db))
    assert exc_info.value.status_code == 404
    assert "Company not found" in exc_info.value.detail


def test_verify_token_success_activates_and_marks_used():
    svc = _svc()
    db = _mock_db()
    fake_token = MagicMock(is_used=False, is_expired=False, user_id=uuid.uuid4(), company_id=uuid.uuid4())
    fake_user = MagicMock(is_verified=False, is_active=False)
    fake_company = MagicMock(is_active=False)
    db.execute = AsyncMock(side_effect=[
        _FakeResult(scalar_one_or_none=fake_token),
        _FakeResult(scalar_one_or_none=fake_user),
        _FakeResult(scalar_one_or_none=fake_company),
    ])

    company, user = asyncio.run(svc.verify_token("tok", db))

    assert user is fake_user
    assert company is fake_company
    assert fake_user.is_verified is True
    assert fake_user.is_active is True
    assert fake_company.is_active is True
    fake_token.mark_as_used.assert_called_once()
    db.commit.assert_awaited()
    assert db.refresh.await_count == 2


# ---------------------------------------------------------------------------
# invalidate_existing_tokens
# ---------------------------------------------------------------------------

def test_invalidate_existing_tokens_marks_all_used():
    svc = _svc()
    db = _mock_db()
    t1, t2 = MagicMock(), MagicMock()
    db.execute = AsyncMock(return_value=_FakeResult(all_=[t1, t2]))

    result = asyncio.run(svc.invalidate_existing_tokens("user@example.com", "company_signup", db))

    assert result is True
    t1.mark_as_used.assert_called_once()
    t2.mark_as_used.assert_called_once()
    db.flush.assert_awaited()


def test_invalidate_existing_tokens_no_tokens_still_returns_true_no_flush():
    svc = _svc()
    db = _mock_db()
    db.execute = AsyncMock(return_value=_FakeResult(all_=[]))

    result = asyncio.run(svc.invalidate_existing_tokens("user@example.com", "company_signup", db))

    assert result is True
    db.flush.assert_not_awaited()


# ---------------------------------------------------------------------------
# resend_verification
# ---------------------------------------------------------------------------

def test_resend_verification_user_not_found_raises_404():
    svc = _svc()
    db = _mock_db()
    db.execute = AsyncMock(return_value=_FakeResult(scalar_one_or_none=None))

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(svc.resend_verification("nope@example.com", db))
    assert exc_info.value.status_code == 404


def test_resend_verification_already_verified_returns_none():
    svc = _svc()
    db = _mock_db()
    fake_user = MagicMock(is_verified=True)
    db.execute = AsyncMock(return_value=_FakeResult(scalar_one_or_none=fake_user))

    result = asyncio.run(svc.resend_verification("user@example.com", db))
    assert result is None


def test_resend_verification_no_company_id_raises_400():
    svc = _svc()
    db = _mock_db()
    fake_user = MagicMock(is_verified=False, company_id=None)
    db.execute = AsyncMock(return_value=_FakeResult(scalar_one_or_none=fake_user))

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(svc.resend_verification("user@example.com", db))
    assert exc_info.value.status_code == 400
    assert "not associated with a company" in exc_info.value.detail


def test_resend_verification_company_not_found_raises_404():
    svc = _svc()
    db = _mock_db()
    fake_user = MagicMock(is_verified=False, company_id=uuid.uuid4())
    db.execute = AsyncMock(side_effect=[
        _FakeResult(scalar_one_or_none=fake_user),
        _FakeResult(scalar_one_or_none=None),
    ])

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(svc.resend_verification("user@example.com", db))
    assert exc_info.value.status_code == 404
    assert "Company not found" in exc_info.value.detail


def test_resend_verification_reactivates_inactive_user_and_company_and_sends():
    svc = _svc()
    db = _mock_db()
    fake_user = MagicMock(is_verified=False, is_active=False, company_id=uuid.uuid4(), id=uuid.uuid4(), name="Jane", email_id="jane@example.com")
    fake_company = MagicMock(is_active=False, name="Acme")
    db.execute = AsyncMock(side_effect=[
        _FakeResult(scalar_one_or_none=fake_user),
        _FakeResult(scalar_one_or_none=fake_company),
        _FakeResult(all_=[]),  # invalidate_existing_tokens lookup (direct call)
        _FakeResult(all_=[]),  # invalidate_existing_tokens lookup (inside generate_verification_token)
    ])

    with patch(f"{MODPATH}.send.settings") as mock_settings, \
         patch(f"{MODPATH}.send.email_service") as mock_email_svc, \
         patch(f"{MODPATH}.send.link_shortener_service") as mock_shortener:
        mock_settings.FRONTEND_URL = "https://app.example.com"
        mock_settings.PLATFORM_URL = "https://app.example.com"
        mock_settings.PLATFORM_NAME = "Accsell"
        mock_settings.SUPPORT_EMAIL = "support@accsell.io"
        mock_settings.EMAIL_VERIFICATION_EXPIRY_HOURS = 24
        mock_email_svc.send_verification_email = MagicMock(return_value=True)
        mock_shortener.shorten = AsyncMock(return_value="https://short.link/xyz")

        result = asyncio.run(svc.resend_verification("jane@example.com", db))

    assert result is True
    assert fake_user.is_active is True
    assert fake_company.is_active is True


# ---------------------------------------------------------------------------
# get_verification_status
# ---------------------------------------------------------------------------

def test_get_verification_status_user_not_found():
    svc = _svc()
    db = _mock_db()
    db.execute = AsyncMock(return_value=_FakeResult(scalar_one_or_none=None))

    result = asyncio.run(svc.get_verification_status("nope@example.com", db))

    assert result == {
        "is_verified": False,
        "is_pending": False,
        "has_valid_token": False,
        "token_expires_at": None,
    }


def test_get_verification_status_verified_user_no_token_lookup_needed():
    svc = _svc()
    db = _mock_db()
    fake_user = MagicMock(is_verified=True)
    fake_token = MagicMock(expires_at=datetime(2099, 1, 1))
    db.execute = AsyncMock(side_effect=[
        _FakeResult(scalar_one_or_none=fake_user),
        _FakeResult(scalar_one_or_none=fake_token),
    ])

    result = asyncio.run(svc.get_verification_status("user@example.com", db))

    assert result["is_verified"] is True
    assert result["is_pending"] is False
    assert result["has_valid_token"] is True
    assert result["token_expires_at"] == fake_token.expires_at


def test_get_verification_status_pending_user_no_valid_token():
    svc = _svc()
    db = _mock_db()
    fake_user = MagicMock(is_verified=False)
    db.execute = AsyncMock(side_effect=[
        _FakeResult(scalar_one_or_none=fake_user),
        _FakeResult(scalar_one_or_none=None),
    ])

    result = asyncio.run(svc.get_verification_status("user@example.com", db))

    assert result["is_verified"] is False
    assert result["is_pending"] is True
    assert result["has_valid_token"] is False
    assert result["token_expires_at"] is None

