"""Tests for the /share-config endpoint (reachable at /api/share-config
through the Next.js frontend's proxy, which strips the /api prefix).

Endpoint URL + auth header are supplied per-request by the caller (same
trust model as the REST API ingest form) — nothing is server-configured."""
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aryx.api.share_config_api import share_config_router


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(share_config_router())
    return TestClient(app, raise_server_exceptions=False)


def _body(**overrides):
    body = {
        "workspace_id": 1, "conversation_id": "abc123",
        "config_json": {"carrier": "Verizon"},
        "endpoint_url": "https://partner.example/ingest",
        "auth_header_name": "Authorization",
        "auth_header_value": "Bearer secret-token",
    }
    body.update(overrides)
    return body


def test_returns_422_when_endpoint_url_missing(client):
    resp = client.post("/share-config", json=_body(endpoint_url=""))
    assert resp.status_code == 422


@pytest.mark.parametrize("url", [
    "http://localhost/steal",
    "http://127.0.0.1/steal",
    "http://169.254.169.254/latest/meta-data/",  # cloud IMDS — the classic SSRF target
    "http://10.0.0.5/internal",
    "ftp://partner.example/ingest",
])
def test_returns_422_for_ssrf_targeting_urls(client, url):
    """Reject the exact SSRF vector Raven review flagged — endpoint_url must
    go through the same blocklist as the REST API ingest form, not just a
    non-empty check."""
    resp = client.post("/share-config", json=_body(endpoint_url=url))
    assert resp.status_code == 422


def test_returns_422_for_host_header_override_via_auth_header_name(client):
    resp = client.post("/share-config", json=_body(auth_header_name="Host"))
    assert resp.status_code == 422


def test_returns_422_for_blocked_extra_header(client):
    resp = client.post("/share-config", json=_body(extra_headers={"Connection": "close"}))
    assert resp.status_code == 422


def test_ssrf_rejection_happens_before_any_outbound_call(client):
    """The blocked request must never reach post_json — confirms this is a
    validation-time rejection, not a caught-and-ignored runtime error."""
    with patch("aryx.api.share_config_api.post_json") as mock_post:
        resp = client.post("/share-config", json=_body(endpoint_url="http://127.0.0.1/steal"))
    assert resp.status_code == 422
    mock_post.assert_not_called()


def test_forwards_payload_with_user_supplied_auth_header(client):
    with patch("aryx.api.share_config_api.post_json") as mock_post:
        mock_post.return_value = {"ok": True}
        resp = client.post("/share-config", json=_body())

    assert resp.status_code == 200
    assert resp.json() == {"shared": True, "partner_response": {"ok": True}}
    call_url, call_body, call_headers = (
        mock_post.call_args[0][0], mock_post.call_args[0][1], mock_post.call_args[1]["headers"])
    assert call_url == "https://partner.example/ingest"
    assert call_body == {"carrier": "Verizon"}, "must post the raw config_json, not an envelope"
    assert call_headers == {"Authorization": "Bearer secret-token"}


def test_custom_auth_header_name_is_respected(client):
    with patch("aryx.api.share_config_api.post_json") as mock_post:
        mock_post.return_value = {"ok": True}
        client.post("/share-config", json=_body(auth_header_name="x-api-key",
                                                 auth_header_value="secret-key"))
    call_headers = mock_post.call_args[1]["headers"]
    assert call_headers == {"x-api-key": "secret-key"}


def test_no_auth_header_sent_when_value_blank(client):
    with patch("aryx.api.share_config_api.post_json") as mock_post:
        mock_post.return_value = {"ok": True}
        client.post("/share-config", json=_body(auth_header_value=""))
    call_headers = mock_post.call_args[1]["headers"]
    assert call_headers == {}


def test_extra_headers_are_forwarded(client):
    with patch("aryx.api.share_config_api.post_json") as mock_post:
        mock_post.return_value = {"ok": True}
        client.post("/share-config", json=_body(extra_headers={"x-tenant": "acme"}))
    call_headers = mock_post.call_args[1]["headers"]
    assert call_headers == {"x-tenant": "acme", "Authorization": "Bearer secret-token"}


def test_502_when_partner_unreachable(client):
    import urllib.error
    with patch("aryx.api.share_config_api.post_json",
               side_effect=urllib.error.URLError("connection refused")):
        resp = client.post("/share-config", json=_body())
    assert resp.status_code == 502
