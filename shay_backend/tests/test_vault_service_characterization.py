"""
Golden-master / characterization tests for app/services/vault_service.py.

Purpose: this file had ZERO dedicated test coverage before this pass. It is
about to be split into a package (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Before the split, we capture
the CURRENT observable behavior of every public method so the split can be
verified to change nothing.

These are characterization tests, not "correctness" tests: assertions match
what the code actually does today, bugs included.

Pattern follows tests/test_channels_characterization.py: no real HTTP calls
(mocked at the exact import path used inside the module under test),
`asyncio.run()` instead of pytest-asyncio (no async plugin installed).

Do not modify app/services/vault_service.py from this file's tests.
"""

from __future__ import annotations

import asyncio
import base64
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


MODPATH = "app.services.vault_service"


def _configured_service():
    """A VaultService with vault_endpoint/vault_token set without touching os.environ."""
    from app.services.vault_service import VaultService
    with patch.dict(os.environ, {
        "CREDENTIALS_MGMT_KV_ENDPOINT": base64.b64encode(b"http://localhost:8200/v1/cubbyhole").decode(),
        "CREDENTIALS_MGMT_VAULT_TOKEN": base64.b64encode(b"test-token").decode(),
        "GIGGSO_CONNECTIONS_PATH_PARAM": "giggso/connections",
    }):
        return VaultService()


# ---------------------------------------------------------------------------
# __init__ / configuration
# ---------------------------------------------------------------------------

def test_init_decodes_base64_env_vars():
    svc = _configured_service()
    assert svc.vault_endpoint == "http://localhost:8200/v1/cubbyhole"
    assert svc.vault_token == "test-token"
    assert svc.giggso_connections_path == "giggso/connections"


def test_init_without_env_vars_leaves_unconfigured():
    from app.services.vault_service import VaultService
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("CREDENTIALS_MGMT_KV_ENDPOINT", None)
        os.environ.pop("CREDENTIALS_MGMT_VAULT_TOKEN", None)
        svc = VaultService()
    assert svc.vault_endpoint is None
    assert svc.vault_token is None


def test_init_default_connections_path():
    from app.services.vault_service import VaultService
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("CREDENTIALS_MGMT_KV_ENDPOINT", None)
        os.environ.pop("CREDENTIALS_MGMT_VAULT_TOKEN", None)
        os.environ.pop("GIGGSO_CONNECTIONS_PATH_PARAM", None)
        svc = VaultService()
    assert svc.giggso_connections_path == "giggso-connections"


def test_init_malformed_base64_leaves_unconfigured():
    from app.services.vault_service import VaultService
    with patch.dict(os.environ, {
        "CREDENTIALS_MGMT_KV_ENDPOINT": "not-valid-base64!!!",
        "CREDENTIALS_MGMT_VAULT_TOKEN": "also-not-valid!!!",
    }):
        svc = VaultService()
    assert svc.vault_endpoint is None
    assert svc.vault_token is None


def test_init_vault_client_request_builds_url_and_headers():
    svc = _configured_service()
    result = svc._init_vault_client_request("user123/abc12345")
    assert result["url"] == "http://localhost:8200/v1/cubbyhole/giggso/connections/user123/abc12345"
    assert result["headers"] == {
        "X-Vault-Token": "test-token",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


# ---------------------------------------------------------------------------
# save_to_vault
# ---------------------------------------------------------------------------

def test_save_to_vault_not_configured_returns_none():
    from app.services.vault_service import VaultService
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("CREDENTIALS_MGMT_KV_ENDPOINT", None)
        os.environ.pop("CREDENTIALS_MGMT_VAULT_TOKEN", None)
        svc = VaultService()
    result = asyncio.run(svc.save_to_vault({"key": "value"}, "id1"))
    assert result is None


def test_save_to_vault_success():
    svc = _configured_service()
    fake_client = AsyncMock()
    fake_response = MagicMock(status_code=200)
    fake_client.post = AsyncMock(return_value=fake_response)
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)

    with patch(f"{MODPATH}.save.httpx.AsyncClient", return_value=fake_client):
        result = asyncio.run(svc.save_to_vault({"key": "value"}, "user1/id1"))

    assert result == "user1/id1"


def test_save_to_vault_non_success_status_returns_none():
    svc = _configured_service()
    fake_client = AsyncMock()
    fake_response = MagicMock(status_code=403, text="forbidden")
    fake_client.post = AsyncMock(return_value=fake_response)
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)

    with patch(f"{MODPATH}.save.httpx.AsyncClient", return_value=fake_client):
        result = asyncio.run(svc.save_to_vault({"key": "value"}, "user1/id1"))

    assert result is None


def test_save_to_vault_exception_returns_none():
    svc = _configured_service()
    with patch(f"{MODPATH}.save.httpx.AsyncClient", side_effect=RuntimeError("boom")):
        result = asyncio.run(svc.save_to_vault({"key": "value"}, "user1/id1"))
    assert result is None


# ---------------------------------------------------------------------------
# retrieve_from_vault
# ---------------------------------------------------------------------------

def test_retrieve_from_vault_not_configured_returns_none():
    from app.services.vault_service import VaultService
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("CREDENTIALS_MGMT_KV_ENDPOINT", None)
        os.environ.pop("CREDENTIALS_MGMT_VAULT_TOKEN", None)
        svc = VaultService()
    result = asyncio.run(svc.retrieve_from_vault("id1"))
    assert result is None


def test_retrieve_from_vault_unwraps_double_nested_data():
    svc = _configured_service()
    fake_client = AsyncMock()
    fake_response = MagicMock(status_code=200)
    fake_response.json = MagicMock(return_value={"data": {"data": {"foo": "bar"}}})
    fake_client.get = AsyncMock(return_value=fake_response)
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)

    with patch(f"{MODPATH}.retrieve.httpx.AsyncClient", return_value=fake_client):
        result = asyncio.run(svc.retrieve_from_vault("id1"))

    assert result == {"foo": "bar"}


def test_retrieve_from_vault_unwraps_single_nested_data():
    svc = _configured_service()
    fake_client = AsyncMock()
    fake_response = MagicMock(status_code=200)
    fake_response.json = MagicMock(return_value={"data": {"foo": "bar"}})
    fake_client.get = AsyncMock(return_value=fake_response)
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)

    with patch(f"{MODPATH}.retrieve.httpx.AsyncClient", return_value=fake_client):
        result = asyncio.run(svc.retrieve_from_vault("id1"))

    assert result == {"foo": "bar"}


def test_retrieve_from_vault_plain_dict_returned_as_is():
    svc = _configured_service()
    fake_client = AsyncMock()
    fake_response = MagicMock(status_code=200)
    fake_response.json = MagicMock(return_value={"foo": "bar"})
    fake_client.get = AsyncMock(return_value=fake_response)
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)

    with patch(f"{MODPATH}.retrieve.httpx.AsyncClient", return_value=fake_client):
        result = asyncio.run(svc.retrieve_from_vault("id1"))

    assert result == {"foo": "bar"}


def test_retrieve_from_vault_non_dict_payload_wrapped():
    svc = _configured_service()
    fake_client = AsyncMock()
    fake_response = MagicMock(status_code=200)
    fake_response.json = MagicMock(return_value="plain-string-payload")
    fake_client.get = AsyncMock(return_value=fake_response)
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)

    with patch(f"{MODPATH}.retrieve.httpx.AsyncClient", return_value=fake_client):
        result = asyncio.run(svc.retrieve_from_vault("id1"))

    assert result == {"value": "plain-string-payload"}


def test_retrieve_from_vault_non_json_response_returns_none():
    svc = _configured_service()
    fake_client = AsyncMock()
    fake_response = MagicMock(status_code=200)
    fake_response.json = MagicMock(side_effect=ValueError("no json"))
    fake_client.get = AsyncMock(return_value=fake_response)
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)

    with patch(f"{MODPATH}.retrieve.httpx.AsyncClient", return_value=fake_client):
        result = asyncio.run(svc.retrieve_from_vault("id1"))

    assert result is None


def test_retrieve_from_vault_404_returns_none():
    svc = _configured_service()
    fake_client = AsyncMock()
    fake_response = MagicMock(status_code=404)
    fake_client.get = AsyncMock(return_value=fake_response)
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)

    with patch(f"{MODPATH}.retrieve.httpx.AsyncClient", return_value=fake_client):
        result = asyncio.run(svc.retrieve_from_vault("id1"))

    assert result is None


def test_retrieve_from_vault_other_error_status_returns_none():
    svc = _configured_service()
    fake_client = AsyncMock()
    fake_response = MagicMock(status_code=500, text="server error")
    fake_client.get = AsyncMock(return_value=fake_response)
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)

    with patch(f"{MODPATH}.retrieve.httpx.AsyncClient", return_value=fake_client):
        result = asyncio.run(svc.retrieve_from_vault("id1"))

    assert result is None


# ---------------------------------------------------------------------------
# delete_from_vault
# ---------------------------------------------------------------------------

def test_delete_from_vault_not_configured_returns_false():
    from app.services.vault_service import VaultService
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("CREDENTIALS_MGMT_KV_ENDPOINT", None)
        os.environ.pop("CREDENTIALS_MGMT_VAULT_TOKEN", None)
        svc = VaultService()
    result = asyncio.run(svc.delete_from_vault("id1"))
    assert result is False


def test_delete_from_vault_success():
    svc = _configured_service()
    fake_client = AsyncMock()
    fake_response = MagicMock(status_code=204)
    fake_client.delete = AsyncMock(return_value=fake_response)
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)

    with patch(f"{MODPATH}.delete.httpx.AsyncClient", return_value=fake_client):
        result = asyncio.run(svc.delete_from_vault("id1"))

    assert result is True


def test_delete_from_vault_404_treated_as_success():
    svc = _configured_service()
    fake_client = AsyncMock()
    fake_response = MagicMock(status_code=404)
    fake_client.delete = AsyncMock(return_value=fake_response)
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)

    with patch(f"{MODPATH}.delete.httpx.AsyncClient", return_value=fake_client):
        result = asyncio.run(svc.delete_from_vault("id1"))

    assert result is True


def test_delete_from_vault_other_error_returns_false():
    svc = _configured_service()
    fake_client = AsyncMock()
    fake_response = MagicMock(status_code=500, text="server error")
    fake_client.delete = AsyncMock(return_value=fake_response)
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)

    with patch(f"{MODPATH}.delete.httpx.AsyncClient", return_value=fake_client):
        result = asyncio.run(svc.delete_from_vault("id1"))

    assert result is False


def test_delete_from_vault_exception_returns_false():
    svc = _configured_service()
    with patch(f"{MODPATH}.delete.httpx.AsyncClient", side_effect=RuntimeError("boom")):
        result = asyncio.run(svc.delete_from_vault("id1"))
    assert result is False


# ---------------------------------------------------------------------------
# generate_vault_unique_id
# ---------------------------------------------------------------------------

def test_generate_vault_unique_id_format():
    svc = _configured_service()
    vault_id = svc.generate_vault_unique_id("5d97b1ed-9c78-4a70-9b4e-74d556d35bad")
    prefix, _, suffix = vault_id.partition("/")
    assert prefix == "5d97b1ed"
    assert len(suffix) == 8


def test_generate_vault_unique_id_is_random_each_call():
    svc = _configured_service()
    id1 = svc.generate_vault_unique_id("user12345")
    id2 = svc.generate_vault_unique_id("user12345")
    assert id1 != id2
    assert id1.split("/")[0] == id2.split("/")[0] == "user1234"
