"""
Golden-master / characterization tests for app/core/encryption_utils.py.

Purpose: encryption_utils.py is 284 lines with zero dedicated test coverage
before this file (tests/test_email_verification_url_safe.py only imports
`encrypt`/`decrypt` incidentally as part of a URL-safety regression test, not
as unit coverage of this module). It is about to be split per
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md.

All tests exercise the real AES-GCM encrypt/decrypt round trip (fast, no
network/DB) using a fixed 64-hex-char test key, matching the shape
tests/conftest.py already sets via SHAY_TOKEN_ENCRYPTION_KEY. No mocking is
needed for the crypto itself; _secret_key()'s validation branches are
exercised by patching app.core.config.settings directly.

Do not modify app/core/encryption_utils.py from this file's tests.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.core.encryption_utils import (
    _secret_key,
    create_encrypted_registration_param,
    create_password_reset_param,
    create_password_reset_url,
    create_registration_url,
    decrypt,
    decrypt_multiple,
    decrypt_password_reset_params,
    decrypt_registration_params,
    decrypt_urlsafe_token,
    encrypt,
    encrypt_multiple,
)


# ---------------------------------------------------------------------------
# _secret_key
# ---------------------------------------------------------------------------
class TestSecretKey:
    def test_raises_when_key_missing(self):
        with patch("app.core.encryption_utils.core.settings") as mock_settings:
            mock_settings.SHAY_TOKEN_ENCRYPTION_KEY = ""
            with pytest.raises(ValueError, match="SHAY_TOKEN_ENCRYPTION_KEY is required"):
                _secret_key()

    def test_raises_when_key_wrong_length(self):
        with patch("app.core.encryption_utils.core.settings") as mock_settings:
            mock_settings.SHAY_TOKEN_ENCRYPTION_KEY = "abcd"
            with pytest.raises(ValueError, match="must be a 64-character hex string"):
                _secret_key()

    def test_returns_32_bytes_for_valid_key(self):
        with patch("app.core.encryption_utils.core.settings") as mock_settings:
            mock_settings.SHAY_TOKEN_ENCRYPTION_KEY = "0" * 64
            assert _secret_key() == bytes.fromhex("0" * 64)
            assert len(_secret_key()) == 32


# ---------------------------------------------------------------------------
# encrypt / decrypt round trip (uses real SHAY_TOKEN_ENCRYPTION_KEY from
# conftest.py's env bootstrap — no patching needed)
# ---------------------------------------------------------------------------
class TestEncryptDecryptRoundTrip:
    def test_round_trip_preserves_data(self):
        assert decrypt(encrypt("hello world")) == "hello world"

    def test_round_trip_empty_string(self):
        assert decrypt(encrypt("")) == ""

    def test_round_trip_unicode(self):
        assert decrypt(encrypt("héllo wörld 日本語")) == "héllo wörld 日本語"

    def test_encrypt_output_is_base64(self):
        import base64
        encrypted = encrypt("test")
        # Should not raise.
        base64.b64decode(encrypted)

    def test_two_encryptions_of_same_data_differ(self):
        """Random IV per call means ciphertext is non-deterministic."""
        assert encrypt("same input") != encrypt("same input")

    def test_decrypt_garbage_raises(self):
        with pytest.raises(Exception, match="Decryption failed"):
            decrypt("not-valid-base64-or-ciphertext!!!")

    def test_encrypt_wraps_exception_with_generic_message(self):
        """Documents current behavior: encrypt() swallows the real cause and
        always raises a generic 'Encryption failed', even for a TypeError
        from a non-str input."""
        with pytest.raises(Exception, match="Encryption failed"):
            encrypt(None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# encrypt_multiple / decrypt_multiple
# ---------------------------------------------------------------------------
class TestMultiple:
    def test_round_trip_multiple_values(self):
        values = ["a@example.com", "invite123", "company-1", "admin"]
        assert decrypt_multiple(encrypt_multiple(values)) == values

    def test_empty_list_round_trips_to_single_empty_string(self):
        """Pre-existing quirk: joining an empty list with SEPARATOR yields
        "", so decrypt_multiple returns [""] (a 1-element list), not []."""
        assert decrypt_multiple(encrypt_multiple([])) == [""]

    def test_values_containing_separator_are_not_distinguishable(self):
        """Pre-existing bug: if a value itself contains the '$@$' separator,
        splitting on decrypt produces MORE fields than were encrypted —
        there's no escaping."""
        values = ["a$@$b", "c"]
        result = decrypt_multiple(encrypt_multiple(values))
        assert result == ["a", "b", "c"]  # 3 fields back, not the original 2


# ---------------------------------------------------------------------------
# registration param / URL helpers
# ---------------------------------------------------------------------------
class TestRegistrationHelpers:
    def test_round_trip_registration_params(self):
        param = create_encrypted_registration_param("a@b.com", "INV1", "co-1", "admin")
        result = decrypt_registration_params(param)
        assert result == {
            "email": "a@b.com",
            "invite_code": "INV1",
            "company_id": "co-1",
            "role": "admin",
        }

    def test_registration_url_is_url_encoded_and_well_formed(self):
        url = create_registration_url("http://localhost:3000", "a@b.com", "INV1", "co-1", "admin")
        assert url.startswith("http://localhost:3000/register?e=")
        # The encrypted param is base64 which may contain '+', '/', '=' —
        # all of those get percent-encoded by quote(..., safe='').
        assert "+" not in url.split("?e=", 1)[1] or "%2B" in url


# ---------------------------------------------------------------------------
# password reset param / URL helpers
# ---------------------------------------------------------------------------
class TestPasswordResetHelpers:
    def test_round_trip_password_reset_params(self):
        param = create_password_reset_param("user-1", "a@b.com", "2026-01-01T00:00:00Z")
        result = decrypt_password_reset_params(param)
        assert result == {
            "user_id": "user-1",
            "email": "a@b.com",
            "timestamp": "2026-01-01T00:00:00Z",
        }

    def test_password_reset_url_is_well_formed(self):
        url = create_password_reset_url("http://localhost:3000", "user-1", "a@b.com", "2026-01-01T00:00:00Z")
        assert url.startswith("http://localhost:3000/reset-password?token=")


# ---------------------------------------------------------------------------
# decrypt_urlsafe_token
# ---------------------------------------------------------------------------
class TestDecryptUrlsafeToken:
    def test_decrypts_plain_encrypted_token(self):
        token = encrypt("secret-payload")
        assert decrypt_urlsafe_token(token) == "secret-payload"

    def test_decrypts_urlsafe_base64_variant(self):
        token = encrypt("secret-payload")
        urlsafe = token.replace("+", "-").replace("/", "_").rstrip("=")
        assert decrypt_urlsafe_token(urlsafe) == "secret-payload"

    def test_decrypts_url_quoted_token(self):
        import urllib.parse
        token = encrypt("secret-payload")
        quoted = urllib.parse.quote(token, safe="")
        assert decrypt_urlsafe_token(quoted) == "secret-payload"

    def test_raises_value_error_for_invalid_token(self):
        with pytest.raises(ValueError, match="Invalid encrypted token"):
            decrypt_urlsafe_token("totally-not-a-real-token")

    def test_raises_value_error_for_empty_token(self):
        with pytest.raises(ValueError, match="Invalid encrypted token"):
            decrypt_urlsafe_token("")
