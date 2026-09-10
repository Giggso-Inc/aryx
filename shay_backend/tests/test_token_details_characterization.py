"""
Golden-master / characterization tests for app/routes/token_details.py.

Purpose: token_details.py is 767 lines with 4 endpoints and had ZERO test
coverage before this file (confirmed: no tests/test_token_details*.py
existed, and grep of tests/ for "token_details" / "updateTokenDetails" /
"llmValidation" turned up nothing). It is about to be split into a package
(see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2).
Before the split, we capture the CURRENT observable behavior of every
endpoint so the split can be verified to change nothing.

These are characterization tests, not "correctness" tests: assertions match
what the code actually does today.

Pattern follows tests/test_channels_characterization.py:
- FastAPI TestClient with `app.include_router(router, prefix=...)`.
- `app.dependency_overrides[get_db] = lambda: mock_db`.
- MagicMock/AsyncMock for services; no real DB, no real HTTP.
- `asyncio.run()` is not needed here (TestClient handles the event loop).

Do not modify app/routes/token_details.py from this file's tests.
"""

from __future__ import annotations

import base64
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _make_client(mock_db):
    from app.core.database import get_db
    from app.routes.token_details import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_db] = lambda: mock_db
    return TestClient(app, raise_server_exceptions=False)


AUTH_HEADERS = {"Authorization": "Bearer test-token"}


def _auth(user, module):
    """Patch get_current_user_required on the specific submodule that owns
    the endpoint under test (each submodule imports it directly) -- see the
    CRITICAL GOTCHA in the compliance plan: patching
    app.routes.token_details.get_current_user_required would NOT affect a
    submodule's own bound reference."""
    return patch(f"app.routes.token_details.{module}.get_current_user_required", new=AsyncMock(return_value=user))


def _uid():
    return str(uuid.uuid4())


def _mock_vault_record(**overrides):
    v = MagicMock()
    v.giggso_vault_id = uuid.uuid4()
    v.vault_unique_id = "vault-unique-001"
    v.company_id = "company-001"
    v.vault_type = "gpt_token"
    v.updated_datetime = None
    v.updated_by = None
    for k, val in overrides.items():
        setattr(v, k, val)
    return v


class _FakeResult:
    def __init__(self, scalar_one_or_none=None):
        self._son = scalar_one_or_none

    def scalar_one_or_none(self):
        return self._son


def _exec_seq(*results):
    return AsyncMock(side_effect=list(results))


# ===========================================================================
# POST /updateTokenDetails — update_token_details
# ===========================================================================

class TestUpdateTokenDetails:
    def _payload(self, company_id, **overrides):
        payload = {
            "token_type": "openai",
            "tokenName": "my-token",
            "api_key": "sk-secret",
            "embedding_model": "text-embedding-ada-002",
            "gpt_model": "gpt-4",
            "companyId": company_id,
        }
        payload.update(overrides)
        return payload

    def test_invalid_company_id_400(self, mock_db, admin_user):
        client = _make_client(mock_db)
        with _auth(admin_user, "update"):
            resp = client.post(
                "/api/v1/updateTokenDetails",
                json=self._payload("not-a-uuid"),
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 400
        assert "Invalid companyId format" in resp.json()["detail"]

    def test_cross_company_403_for_non_admin(self, mock_db, regular_user):
        regular_user.company_id = "other-company"
        client = _make_client(mock_db)
        with _auth(regular_user, "update"):
            resp = client.post(
                "/api/v1/updateTokenDetails",
                json=self._payload(_uid()),
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 403

    def test_azure_missing_fields_400(self, mock_db, admin_user):
        admin_user.role = "admin"  # admin bypasses the company mismatch check
        client = _make_client(mock_db)
        with _auth(admin_user, "update"):
            resp = client.post(
                "/api/v1/updateTokenDetails",
                json=self._payload(_uid(), token_type="azure"),
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 400
        assert "deploymentName" in resp.json()["detail"]

    def test_vault_record_not_found_404(self, mock_db, admin_user):
        admin_user.company_id = "company-001"
        company_id = "not-used"
        admin_user.role = "admin"  # admin bypasses the company mismatch check
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        client = _make_client(mock_db)
        with _auth(admin_user, "update"):
            resp = client.post(
                "/api/v1/updateTokenDetails",
                json=self._payload(_uid()),
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 404

    def test_happy_path(self, mock_db, admin_user):
        admin_user.role = "admin"
        vault_record = _mock_vault_record()
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=vault_record))
        client = _make_client(mock_db)
        with _auth(admin_user, "update"), \
                patch("app.routes.token_details.update.vault_service.save_to_vault", new=AsyncMock(return_value="vault-unique-001")):
            resp = client.post(
                "/api/v1/updateTokenDetails",
                json=self._payload(_uid()),
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["vault_unique_id"] == "vault-unique-001"
        assert body["data"]["giggso_vault_id"] == str(vault_record.giggso_vault_id)

    def test_save_to_vault_failure_500(self, mock_db, admin_user):
        """Characterization of a real quirk: the "Failed to update token
        details in vault" 500 is raised as an explicit HTTPException, which
        the surrounding `except HTTPException: raise` re-raises untouched --
        it never reaches the generic `except Exception` branch that calls
        db.rollback(). So this particular 500 path does NOT roll back,
        unlike an unexpected exception would. Documented as-is."""
        admin_user.role = "admin"
        vault_record = _mock_vault_record()
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=vault_record))
        client = _make_client(mock_db)
        with _auth(admin_user, "update"), \
                patch("app.routes.token_details.update.vault_service.save_to_vault", new=AsyncMock(return_value=None)):
            resp = client.post(
                "/api/v1/updateTokenDetails",
                json=self._payload(_uid()),
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 500
        mock_db.rollback.assert_not_awaited()


# ===========================================================================
# POST /fetchTokenDetails — fetch_token_details
# ===========================================================================

class TestFetchTokenDetails:
    def test_cross_company_403_for_non_admin(self, mock_db, regular_user):
        regular_user.company_id = "other-company"
        client = _make_client(mock_db)
        with _auth(regular_user, "fetch"):
            resp = client.post(
                "/api/v1/fetchTokenDetails",
                json={"companyId": _uid()},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 403

    def test_vault_record_not_found_404(self, mock_db, admin_user):
        admin_user.role = "admin"
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        client = _make_client(mock_db)
        with _auth(admin_user, "fetch"):
            resp = client.post(
                "/api/v1/fetchTokenDetails",
                json={"companyId": _uid()},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 404

    def test_happy_path_decodes_and_reshapes(self, mock_db, admin_user):
        admin_user.role = "admin"
        vault_record = _mock_vault_record()
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=vault_record))
        encoded_key = base64.b64encode(b"sk-secret").decode("utf-8")
        vault_payload = {
            "openaiToken": encoded_key,
            "tokenType": "azure",
            "model": "gpt-4",
            "apiVersion": "2024-01-01",
            "embeddingsDeploymentName": "embed-1",
            "companyId": "company-001",
        }
        client = _make_client(mock_db)
        with _auth(admin_user, "fetch"), \
                patch("app.routes.token_details.fetch.vault_service.retrieve_from_vault", new=AsyncMock(return_value=vault_payload)):
            resp = client.post(
                "/api/v1/fetchTokenDetails",
                json={"companyId": _uid()},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 200
        body = resp.json()["data"]["token_details"]
        assert body["api_key"] == "sk-secret"
        assert body["token_type"] == "azureopenai"
        assert body["gpt_model"] == "gpt-4"

    def test_vault_lookup_not_found_in_external_vault_404(self, mock_db, admin_user):
        admin_user.role = "admin"
        vault_record = _mock_vault_record()
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=vault_record))
        client = _make_client(mock_db)
        with _auth(admin_user, "fetch"), \
                patch("app.routes.token_details.fetch.vault_service.retrieve_from_vault", new=AsyncMock(return_value=None)):
            resp = client.post(
                "/api/v1/fetchTokenDetails",
                json={"companyId": _uid()},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 404


# ===========================================================================
# DELETE /deleteTokenDetails — delete_token_details
# ===========================================================================

class TestDeleteTokenDetails:
    def test_cross_company_403_for_non_admin(self, mock_db, regular_user):
        regular_user.company_id = "other-company"
        client = _make_client(mock_db)
        with _auth(regular_user, "delete"):
            resp = client.request(
                "DELETE",
                "/api/v1/deleteTokenDetails",
                json={"companyId": _uid()},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 403

    def test_vault_record_not_found_404(self, mock_db, admin_user):
        admin_user.role = "admin"
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        client = _make_client(mock_db)
        with _auth(admin_user, "delete"):
            resp = client.request(
                "DELETE",
                "/api/v1/deleteTokenDetails",
                json={"companyId": _uid()},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 404

    def test_happy_path(self, mock_db, admin_user):
        admin_user.role = "admin"
        vault_record = _mock_vault_record()
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=vault_record))
        client = _make_client(mock_db)
        with _auth(admin_user, "delete"), \
                patch("app.routes.token_details.delete.vault_service.delete_from_vault", new=AsyncMock(return_value=True)):
            resp = client.request(
                "DELETE",
                "/api/v1/deleteTokenDetails",
                json={"companyId": _uid()},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 200
        assert resp.json()["data"]["deleted"] is True
        mock_db.delete.assert_awaited_with(vault_record)

    def test_vault_delete_failure_500(self, mock_db, admin_user):
        """Same quirk as TestUpdateTokenDetails.test_save_to_vault_failure_500:
        the explicit HTTPException(500) for a failed vault delete is
        re-raised by `except HTTPException: raise` before ever reaching the
        rollback in `except Exception`. Documented as-is."""
        admin_user.role = "admin"
        vault_record = _mock_vault_record()
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=vault_record))
        client = _make_client(mock_db)
        with _auth(admin_user, "delete"), \
                patch("app.routes.token_details.delete.vault_service.delete_from_vault", new=AsyncMock(return_value=False)):
            resp = client.request(
                "DELETE",
                "/api/v1/deleteTokenDetails",
                json={"companyId": _uid()},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 500
        mock_db.rollback.assert_not_awaited()


# ===========================================================================
# POST /llmValidation/gpt-token-validation — llm_validation
# ===========================================================================

class TestLlmValidation:
    def _payload(self, llm_type, **overrides):
        payload = {
            "llmType": llm_type,
            "llmApiKey": base64.b64encode(b"secret-key").decode("utf-8"),
            "llmModelName": "gpt-4",
        }
        payload.update(overrides)
        return payload

    def test_invalid_base64_key_payload_issue_400(self, mock_db):
        client = _make_client(mock_db)
        resp = client.post(
            "/api/v1/llmValidation/gpt-token-validation",
            json=self._payload("chatgpt", llmApiKey="not-valid-base64!!"),
        )
        assert resp.status_code == 200  # endpoint always returns 200 HTTP, status is in body
        body = resp.json()["data"]
        assert body["status"] == "failed"
        assert body["type"] == "payload_issue"

    def test_unsupported_provider_returns_failed_body(self, mock_db):
        client = _make_client(mock_db)
        resp = client.post(
            "/api/v1/llmValidation/gpt-token-validation",
            json=self._payload("unknown-provider"),
        )
        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["status"] == "failed"
        assert body["type"] == "unsupported_provider"

    def test_azure_missing_fields_returns_failed_body(self, mock_db):
        client = _make_client(mock_db)
        resp = client.post(
            "/api/v1/llmValidation/gpt-token-validation",
            json=self._payload("azureopenai"),
        )
        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["status"] == "failed"
        assert body["type"] == "payload_issue"
        assert "endpoint" in body["message"]

    def test_azure_happy_path(self, mock_db):
        client = _make_client(mock_db)
        with patch("app.services.llm_validation_service.update_azure_openai_chat", return_value="ok"):
            resp = client.post(
                "/api/v1/llmValidation/gpt-token-validation",
                json=self._payload(
                    "azureopenai",
                    llmApiVersion="2024-01-01",
                    llmEndpoint="https://example.openai.azure.com",
                ),
            )
        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["status"] == "success"

    def test_chatgpt_happy_path(self, mock_db):
        client = _make_client(mock_db)
        with patch("app.services.llm_validation_service.update_openai_chat", return_value="ok"):
            resp = client.post(
                "/api/v1/llmValidation/gpt-token-validation",
                json=self._payload("chatgpt"),
            )
        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["status"] == "success"

    def test_chatgpt_rate_limit_returns_quota_issue(self, mock_db):
        request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
        response = httpx.Response(status_code=429, request=request)
        from openai import RateLimitError
        err = RateLimitError("rate limited", response=response, body=None)
        client = _make_client(mock_db)
        with patch("app.services.llm_validation_service.update_openai_chat", side_effect=err):
            resp = client.post(
                "/api/v1/llmValidation/gpt-token-validation",
                json=self._payload("chatgpt"),
            )
        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["status"] == "failed"
        assert body["type"] == "quota_issue"
        assert resp.json()["code"] == 429

    def test_gemini_happy_path(self, mock_db):
        client = _make_client(mock_db)
        with patch("app.services.llm_validation_service.validate_gemini", return_value="ok"):
            resp = client.post(
                "/api/v1/llmValidation/gpt-token-validation",
                json=self._payload("gemini"),
            )
        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["status"] == "success"

    def test_gemini_invalid_argument_returns_invalid_key(self, mock_db):
        from google.api_core.exceptions import InvalidArgument
        client = _make_client(mock_db)
        with patch("app.services.llm_validation_service.validate_gemini", side_effect=InvalidArgument("bad key")):
            resp = client.post(
                "/api/v1/llmValidation/gpt-token-validation",
                json=self._payload("gemini"),
            )
        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["status"] == "failed"
        assert body["type"] == "invalid_key"
