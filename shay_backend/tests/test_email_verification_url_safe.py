"""
Unit tests for email verification URL-safe base64 changes.

Covers:
- Encrypted token written into the verification link uses URL-safe base64
  (no +, /, = chars) so copy-pasted URLs don't break on path splitting
- verification_data uses SUPPORT_EMAIL, not SMTP_FROM

No DB required — email_service is mocked.
"""
import asyncio
import base64
import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch, AsyncMock

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://accsell_user:accsell_pass@localhost:5433/accsell_test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-tests-only")
sys.modules.setdefault("socketio", MagicMock())
sys.modules.setdefault("python_socketio", MagicMock())

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.encryption_utils import encrypt
from app.models.email_verification_token import EmailVerificationToken


def _url_safe_convert(standard_b64: str) -> str:
    """Mirrors the conversion in send_verification_email."""
    return standard_b64.replace('+', '-').replace('/', '_').replace('=', '')


# ── URL-safe base64 encoding ──────────────────────────────────────────────────

def test_url_safe_token_contains_no_plus():
    """Token in verification link must not contain '+' (would percent-encode in URLs)."""
    token = "test-verification-token-12345"
    encrypted = encrypt(token)
    url_safe = _url_safe_convert(encrypted)
    assert '+' not in url_safe


def test_url_safe_token_contains_no_slash():
    """Token must not contain '/' (browser decodes %2F in paths, splitting the route)."""
    token = "test-verification-token-12345"
    encrypted = encrypt(token)
    url_safe = _url_safe_convert(encrypted)
    assert '/' not in url_safe


def test_url_safe_token_contains_no_padding():
    """Token must not contain '=' padding (invalid in URL paths)."""
    token = "test-verification-token-12345"
    encrypted = encrypt(token)
    url_safe = _url_safe_convert(encrypted)
    assert '=' not in url_safe


def test_url_safe_token_is_valid_url_safe_base64():
    """Token must only contain URL-safe base64 characters (A-Z a-z 0-9 - _)."""
    import re
    token = "another-verification-token-xyz"
    encrypted = encrypt(token)
    url_safe = _url_safe_convert(encrypted)
    assert re.fullmatch(r'[A-Za-z0-9\-_]+', url_safe), (
        f"Token contains non-URL-safe chars: {url_safe!r}"
    )


def test_url_safe_token_round_trips_to_original():
    """
    URL-safe token must round-trip back to the original after re-normalising
    to standard base64 — matching the frontend normalization in verify-email.tsx.
    """
    from app.core.encryption_utils import decrypt

    original = "my-verification-token-abc"
    encrypted = encrypt(original)
    url_safe = _url_safe_convert(encrypted)

    # Frontend normalization (verify-email.tsx lines 84-85)
    std = url_safe.replace('-', '+').replace('_', '/')
    padding = '=' * ((4 - len(std) % 4) % 4)
    standard_b64 = std + padding

    decrypted = decrypt(standard_b64)
    assert decrypted == original


# ── SUPPORT_EMAIL in verification_data ───────────────────────────────────────

def test_send_verification_email_uses_support_email_not_smtp_from():
    """
    verification_data['support_email'] must come from settings.SUPPORT_EMAIL,
    not settings.SMTP_FROM — so the correct support address appears in the email.
    """
    from app.services.email_verification_service import EmailVerificationService

    svc = EmailVerificationService()
    captured: dict = {}

    def mock_send(to_email, verification_data, platform_url):
        captured.update(verification_data)
        return True

    with patch("app.services.email_verification_service.settings") as mock_settings, \
         patch("app.services.email_verification_service.email_service") as mock_email_svc, \
         patch("app.services.email_verification_service.link_shortener_service") as mock_shortener:
        mock_settings.PLATFORM_URL   = "https://app.example.com"
        mock_settings.PLATFORM_NAME  = "Accsell"
        mock_settings.SUPPORT_EMAIL  = "support@accsell.io"
        mock_settings.SMTP_FROM      = "noreply@accsell.io"
        mock_settings.EMAIL_VERIFICATION_EXPIRY_HOURS = 24
        mock_email_svc.send_verification_email = mock_send
        mock_shortener.shorten = AsyncMock(return_value="https://short.link/abc")

        asyncio.run(svc.send_verification_email(
            email="user@example.com",
            token="tok-123",
            company_name="Acme Corp",
        ))

    assert captured.get("support_email") == "support@accsell.io"
    assert captured.get("support_email") != "noreply@accsell.io"


def test_send_verification_email_normalizes_relative_platform_url():
    """
    Relative platform URLs must be expanded to the configured frontend host so
    verification links in email always include a real origin.
    """
    from app.services.email_verification_service import EmailVerificationService

    svc = EmailVerificationService()
    captured: dict = {}

    def mock_send(to_email, verification_data, platform_url):
        captured["platform_url"] = platform_url
        captured["verification_link"] = verification_data["verification_link"]
        return True

    async def passthrough_shortener(url, db=None):
        return url

    with patch("app.services.email_verification_service.settings") as mock_settings, \
         patch("app.services.email_verification_service.email_service") as mock_email_svc, \
         patch("app.services.email_verification_service.link_shortener_service") as mock_shortener:
        mock_settings.FRONTEND_URL = "https://app.aryx.com"
        mock_settings.PLATFORM_URL = "http://localhost:3000"
        mock_settings.PLATFORM_NAME = "Aryx"
        mock_settings.SUPPORT_EMAIL = "support@aryx.com"
        mock_settings.EMAIL_VERIFICATION_EXPIRY_HOURS = 24
        mock_email_svc.send_verification_email = mock_send
        mock_shortener.shorten = AsyncMock(side_effect=passthrough_shortener)

        asyncio.run(svc.send_verification_email(
            email="user@example.com",
            token="tok-123",
            company_name="Aryx Corp",
            platform_url="/",
        ))

    assert captured["platform_url"] == "https://app.aryx.com"
    assert captured["verification_link"].startswith("https://app.aryx.com/verifyEmail/")


def test_email_verification_token_handles_aware_expiry_datetime():
    """Mixed aware/naive datetimes should not crash token expiry checks."""
    token = EmailVerificationToken(
        email="user@example.com",
        token="tok-123",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        is_used=False,
    )

    assert token.is_valid is True
    assert token.is_expired is False
