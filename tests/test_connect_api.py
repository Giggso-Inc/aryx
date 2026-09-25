"""Tests for the /admin/connect, /admin/discover, /admin/ingest/multi auth gate.

CPQ_Hardcode_Audit_dev_oci_2026-09-25.md T11: unlike their siblings in
admin_api.py/ontology_api.py, these three routes carried no require_api_key/
write_api_key dependency — a live database-port probe (and, for
dialect="sqlite", arbitrary local file access) reachable with zero
authentication whenever the global ARYX_API_AUTH middleware is ever
optional/off, which the shipped .env.example already demonstrates is
possible.
"""
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aryx.api.connect_api import connect_router


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(connect_router())
    return TestClient(app, raise_server_exceptions=False)


def test_connect_no_key_returns_401(client):
    with patch("aryx.api.security._verify_key", return_value=False):
        resp = client.post("/admin/connect", json={"dialect": "sqlite", "database": "/etc/passwd"})
    assert resp.status_code == 401


def test_discover_no_key_returns_401(client):
    with patch("aryx.api.security._verify_key", return_value=False):
        resp = client.post("/admin/discover", json={"connection_id": "x", "context": "y"})
    assert resp.status_code == 401


def test_ingest_multi_no_key_returns_401(client):
    with patch("aryx.api.security._verify_key", return_value=False):
        resp = client.post("/admin/ingest/multi", json={"connection_id": "x", "tables": []})
    assert resp.status_code == 401


def test_connect_valid_key_proceeds_past_auth(client):
    """A valid key clears the auth gate — the subsequent connection failure
    (no real DB at this address) proves auth was not what stopped the request."""
    with patch("aryx.api.security._verify_key", return_value=True):
        resp = client.post(
            "/admin/connect",
            json={"dialect": "postgresql", "host": "nonexistent-host-for-test", "database": "db"},
            headers={"x-aryx-api-key": "valid-key"},
        )
    assert resp.status_code == 400
    assert "connection failed" in resp.json()["detail"]
