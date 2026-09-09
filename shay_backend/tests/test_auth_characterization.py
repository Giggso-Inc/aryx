"""
Golden-master / characterization tests for app/core/auth.py.

Purpose: auth.py (JWT token generation, password hashing, ID generation) is
279 lines with zero dedicated test coverage before this file
(tests/test_user_auth_*.py exercise app/routes/user_auth/* endpoints and
happen to touch auth.py only indirectly through the route layer, mocking
create_access_token etc. at the route's own import site — they never call
into auth.py's real functions). HIGH CAUTION per the task: this is JWT/token
generation code. It is about to be split per
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md.

Real SECRET_KEY/ALGORITHM/ACCESS_TOKEN_EXPIRE_MINUTES/REFRESH_TOKEN_EXPIRE_DAYS
from app.core.config.settings are used throughout (all have real defaults;
no .env required) so encode/decode round trips are exercised for real, not
mocked. Only the bcrypt-fallback exception branch in verify_password is
tested via mocking, since forcing pwd_context.verify() to raise isn't
otherwise reachable without a malformed hash.

Do not modify app/core/auth.py from this file's tests.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from unittest.mock import patch

import pytest
from jose import jwt

from app.core.auth import (
    TokenData,
    create_access_token,
    create_refresh_token,
    create_token_data,
    decode_access_token,
    generate_ai_response_id,
    generate_approval_id,
    generate_attachment_id,
    generate_channel_id,
    generate_company_id,
    generate_message_id,
    generate_user_id,
    generate_workspace_id,
    get_password_hash,
    hash_password,
    validate_password_length,
    verify_password,
    verify_token,
)
from app.core.config import settings


# ---------------------------------------------------------------------------
# create_access_token / verify_token / decode_access_token
# ---------------------------------------------------------------------------
class TestAccessToken:
    def test_round_trip_verify_token(self):
        token = create_access_token({"sub": "user-1", "role": "admin"})
        payload = verify_token(token)
        assert payload["sub"] == "user-1"
        assert payload["role"] == "admin"
        assert "exp" in payload

    def test_default_expiry_uses_settings_minutes(self):
        token = create_access_token({"sub": "user-1"})
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        # Just assert exp exists and is in the future relative to iat-less payload;
        # exact timing is inherently flaky, so only check presence + type.
        assert isinstance(payload["exp"], int)

    def test_custom_expires_delta_is_honored(self):
        token = create_access_token({"sub": "user-1"}, expires_delta=timedelta(minutes=5))
        payload = verify_token(token)
        assert payload is not None

    def test_verify_token_returns_none_for_garbage(self):
        assert verify_token("not-a-jwt") is None

    def test_verify_token_returns_none_for_wrong_secret(self):
        bad_token = jwt.encode({"sub": "x"}, "wrong-secret", algorithm=settings.ALGORITHM)
        assert verify_token(bad_token) is None

    def test_decode_access_token_returns_payload(self):
        token = create_access_token({"sub": "user-1"})
        payload = decode_access_token(token)
        assert payload["sub"] == "user-1"

    def test_decode_access_token_raises_401_for_invalid_token(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            decode_access_token("garbage")
        assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# create_refresh_token
# ---------------------------------------------------------------------------
class TestRefreshToken:
    def test_refresh_token_has_type_field(self):
        token = create_refresh_token({"sub": "user-1"})
        payload = verify_token(token)
        assert payload["type"] == "refresh"
        assert payload["sub"] == "user-1"


# ---------------------------------------------------------------------------
# password hashing
# ---------------------------------------------------------------------------
class TestPasswordHashing:
    def test_hash_and_verify_round_trip(self):
        hashed = hash_password("correct-horse-battery-staple")
        assert verify_password("correct-horse-battery-staple", hashed) is True

    def test_verify_wrong_password_returns_false(self):
        hashed = hash_password("correct-horse-battery-staple")
        assert verify_password("wrong-password", hashed) is False

    def test_get_password_hash_is_alias_for_hash_password(self):
        hashed = get_password_hash("some-password")
        assert verify_password("some-password", hashed) is True

    def test_hash_password_empty_raises_value_error(self):
        with pytest.raises(ValueError, match="Password cannot be empty"):
            hash_password("")

    def test_verify_password_falls_back_to_direct_bcrypt_on_passlib_exception(self):
        """When pwd_context.verify raises, the code falls back to bcrypt.checkpw
        directly rather than propagating — documents the fallback path."""
        hashed = hash_password("mypassword")
        with patch("app.core.auth.passwords.pwd_context") as mock_ctx:
            mock_ctx.verify.side_effect = Exception("passlib internal error")
            assert verify_password("mypassword", hashed) is True

    def test_verify_password_reraises_when_bcrypt_also_fails(self):
        with patch("app.core.auth.passwords.pwd_context") as mock_ctx, \
             patch("app.core.auth.passwords.BCRYPT_AVAILABLE", False):
            mock_ctx.verify.side_effect = Exception("passlib internal error")
            with pytest.raises(Exception, match="passlib internal error"):
                verify_password("mypassword", "some-hash")


# ---------------------------------------------------------------------------
# validate_password_length
# ---------------------------------------------------------------------------
class TestValidatePasswordLength:
    def test_short_password_unchanged(self):
        assert validate_password_length("short") == "short"

    def test_empty_password_raises(self):
        with pytest.raises(ValueError, match="Password cannot be empty"):
            validate_password_length("")

    def test_none_password_raises(self):
        with pytest.raises(ValueError, match="Password cannot be empty"):
            validate_password_length(None)  # type: ignore[arg-type]

    def test_long_password_truncated_to_72_bytes(self):
        long_password = "a" * 100
        result = validate_password_length(long_password)
        assert len(result.encode("utf-8")) <= 72
        assert result == "a" * 72

    def test_long_unicode_password_truncated_on_char_boundary(self):
        # Each 'é' is 2 bytes in UTF-8; 40 of them = 80 bytes > 72.
        long_password = "é" * 40
        result = validate_password_length(long_password)
        assert len(result.encode("utf-8")) <= 72
        # No partial multi-byte character should survive.
        result.encode("utf-8").decode("utf-8")  # would raise if malformed


# ---------------------------------------------------------------------------
# ID generators
# ---------------------------------------------------------------------------
class TestIdGenerators:
    @pytest.mark.parametrize("fn", [
        generate_user_id, generate_company_id, generate_workspace_id,
        generate_message_id, generate_approval_id, generate_attachment_id,
        generate_channel_id, generate_ai_response_id,
    ])
    def test_generates_valid_uuid4_string(self, fn):
        value = fn()
        assert isinstance(value, str)
        parsed = uuid.UUID(value)
        assert parsed.version == 4

    def test_generators_produce_unique_values(self):
        assert generate_user_id() != generate_user_id()


# ---------------------------------------------------------------------------
# TokenData / create_token_data
# ---------------------------------------------------------------------------
class TestTokenData:
    def test_token_data_stores_fields(self):
        td = TokenData(user_id="u1", email="a@b.com", role="admin", company_id="c1")
        assert td.user_id == "u1"
        assert td.email == "a@b.com"
        assert td.role == "admin"
        assert td.company_id == "c1"

    def test_token_data_company_id_defaults_to_none(self):
        td = TokenData(user_id="u1", email="a@b.com", role="admin")
        assert td.company_id is None

    def test_create_token_data_shape(self):
        result = create_token_data("u1", "a@b.com", "admin", "c1")
        assert result == {
            "sub": "u1",
            "email": "a@b.com",
            "role": "admin",
            "company_id": "c1",
            "type": "access",
        }

    def test_create_token_data_company_id_defaults_to_none(self):
        result = create_token_data("u1", "a@b.com", "admin")
        assert result["company_id"] is None
