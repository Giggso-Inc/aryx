"""Unit tests for Aryx API header authentication."""

from __future__ import annotations

from unittest.mock import patch

from starlette.requests import Request

from aryx.api.security import _has_authenticated_header


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
