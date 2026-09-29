"""Unit tests for Aryx API header authentication."""

from __future__ import annotations

from unittest.mock import patch

from starlette.requests import Request

from aryx.api.security import _has_authenticated_header, _verify_key


def _request(headers: dict[str, str]) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/ask",
            "headers": [
                (key.lower().encode("latin-1"), value.encode("latin-1"))
                for key, value in headers.items()
            ],
        }
    )


def test_arbitrary_bearer_token_is_not_treated_as_authenticated():
    with patch("aryx.api.security._verify_key", return_value=False):
        assert _has_authenticated_header(_request({"Authorization": "Bearer junk"})) is False


def test_verified_internal_api_key_is_authenticated():
    with patch("aryx.api.security._verify_key", return_value=True):
        assert _has_authenticated_header(_request({"x-aryx-api-key": "valid-key"})) is True


def test_env_internal_api_key_is_authenticated(monkeypatch):
    monkeypatch.setenv("ARYX_INTERNAL_API_KEY", "bridge-key-1234567890")
    assert _has_authenticated_header(_request({"x-aryx-api-key": "bridge-key-1234567890"})) is True


def test_verify_key_accepts_configured_internal_key(monkeypatch):
    monkeypatch.setenv("ARYX_INTERNAL_API_KEY", "bridge-key-1234567890")
    assert _verify_key("bridge-key-1234567890") is True


# CPQ_Hardcode_Audit_dev_oci_2026-09-25.md T11: all three .env.example*
# files ship the same ARYX_INTERNAL_API_KEY placeholder -- a deployment
# that never rotates it must not have that literal value work as a real
# shared secret.

def test_verify_key_rejects_the_shipped_placeholder_value(monkeypatch):
    # get_settings is imported inside _verify_key; patch its source location
    # (same pattern as test_verify_key_fails_closed_on_store_exception in
    # test_auth.py) to force the McpTokenStore fallthrough to fail closed,
    # isolating whether the placeholder check itself correctly skipped the
    # internal-key acceptance branch.
    monkeypatch.setenv("ARYX_INTERNAL_API_KEY", "change_me_internal_aryx_token")
    with patch("aryx.config.get_settings", side_effect=RuntimeError("no db")):
        assert _verify_key("change_me_internal_aryx_token") is False


def test_verify_key_rejects_a_too_short_configured_key(monkeypatch):
    monkeypatch.setenv("ARYX_INTERNAL_API_KEY", "short")
    with patch("aryx.config.get_settings", side_effect=RuntimeError("no db")):
        assert _verify_key("short") is False
