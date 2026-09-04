"""
Gap-fill golden-master / characterization tests for
app/services/ml_service.py.

Purpose: ml_service.py is 478 lines. tests/test_ml_service_embedd_type.py
already covers `get_embedd_type_from_file_type` fully, and
`MLService.request_embedding_processing`'s textual/tabular/default
embedd_type, embedded_vault_unique_ids, jwt_token header, API-error,
timeout, and connection-error paths. This file adds ONLY what that file
does not cover, ahead of the file's split into a package (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a):

  - `extract_table_names_from_datasources` (module function, zero prior
    coverage)
  - `MLService.__init__` defaults (getattr fallback behavior)
  - `request_embedding_processing`: table_name / table_names / thread_id /
    openai_vault_token payload construction, the JSON-decode-error branch,
    and the generic-Exception branch
  - `check_embedding_status` (entirely uncovered)
  - `delete_embeddings` (entirely uncovered)

These are characterization tests: assertions match current behavior,
including bugs. Notably `check_embedding_status` and `delete_embeddings`
build `auth_token`/headers using `self.ml_api_key` (not `settings.ML_API_KEY`
directly as `request_embedding_processing` does) — characterized as-is.

Existing tests use `@pytest.mark.asyncio` directly (no explicit event-loop
fixture), so this file follows the same style rather than introducing
`asyncio.run()` — pytest-asyncio is confirmed installed and active for this
suite (tests/test_ml_service_embedd_type.py passes under it).
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.ml_service import (
    MLService,
    extract_table_names_from_datasources,
)


# ---------------------------------------------------------------------------
# extract_table_names_from_datasources
# ---------------------------------------------------------------------------
def test_extract_table_names_dict_with_config():
    datasources = [{"config": {"tableName": "users"}}]
    assert extract_table_names_from_datasources(datasources) == ["users"]


def test_extract_table_names_dict_falls_back_to_metadata():
    datasources = [{"datasource_metadata": {"tableName": "orders"}}]
    assert extract_table_names_from_datasources(datasources) == ["orders"]


def test_extract_table_names_dict_config_present_but_no_tablename_falls_back():
    datasources = [{"config": {}, "datasource_metadata": {"tableName": "fallback_table"}}]
    assert extract_table_names_from_datasources(datasources) == ["fallback_table"]


def test_extract_table_names_orm_model_metadata_attr():
    class FakeDatasource:
        datasource_metadata = {"tableName": "orm_table"}
        config = None

    assert extract_table_names_from_datasources([FakeDatasource()]) == ["orm_table"]


def test_extract_table_names_orm_model_config_attr_fallback():
    class FakeDatasource:
        config = {"tableName": "config_table"}

    assert extract_table_names_from_datasources([FakeDatasource()]) == ["config_table"]


def test_extract_table_names_dedupes_and_skips_missing():
    datasources = [
        {"config": {"tableName": "t1"}},
        {"config": {"tableName": "t1"}},
        {"config": {}},  # no tableName anywhere -> skipped
        {},
    ]
    assert extract_table_names_from_datasources(datasources) == ["t1"]


def test_extract_table_names_empty_list():
    assert extract_table_names_from_datasources([]) == []


# ---------------------------------------------------------------------------
# MLService.__init__ defaults
# ---------------------------------------------------------------------------
def test_ml_service_init_uses_settings_when_present():
    with patch("app.services.ml_service.client.settings") as mock_settings:
        mock_settings.ML_API_URL = "https://custom.example.com"
        mock_settings.ML_API_KEY = "custom-key"
        svc = MLService()

    assert svc.ml_api_url == "https://custom.example.com"
    assert svc.ml_api_key == "custom-key"
    assert svc.timeout is None


def test_ml_service_init_falls_back_to_defaults_when_settings_missing_attrs():
    class BareSettings:
        pass

    with patch("app.services.ml_service.client.settings", BareSettings()):
        svc = MLService()

    assert svc.ml_api_url == "https://dev-fourd.shay-ai.com"
    assert svc.ml_api_key == ""


# ---------------------------------------------------------------------------
# request_embedding_processing — payload construction gaps
# ---------------------------------------------------------------------------
def _ok_response(payload=None):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = payload or {"status": "success"}
    mock_response.text = json.dumps(payload or {"status": "success"})
    mock_response.headers = {}
    return mock_response


@pytest.mark.asyncio
async def test_request_embedding_processing_table_names_wins_over_table_name():
    svc = MLService()
    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.post.return_value = _ok_response()

        await svc.request_embedding_processing(
            vault_unique_ids=["v1"],
            user_id="u1",
            company_id="c1",
            channel_id="ch1",
            table_name="single_table",
            table_names=["t1", "t2"],
        )

        call_args = mock_client.return_value.__aenter__.return_value.post.call_args
        payload = call_args[1]["json"]
        assert payload["tableNames"] == ["t1", "t2"]
        assert "tableName" not in payload


@pytest.mark.asyncio
async def test_request_embedding_processing_table_name_used_when_no_table_names():
    svc = MLService()
    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.post.return_value = _ok_response()

        await svc.request_embedding_processing(
            vault_unique_ids=["v1"],
            user_id="u1",
            company_id="c1",
            channel_id="ch1",
            table_name="single_table",
        )

        call_args = mock_client.return_value.__aenter__.return_value.post.call_args
        payload = call_args[1]["json"]
        assert payload["tableName"] == "single_table"
        assert "tableNames" not in payload


@pytest.mark.asyncio
async def test_request_embedding_processing_thread_id_and_openai_vault_token_included():
    svc = MLService()
    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.post.return_value = _ok_response()

        await svc.request_embedding_processing(
            vault_unique_ids=["v1"],
            user_id="u1",
            company_id="c1",
            channel_id="ch1",
            thread_id="thread-1",
            openai_vault_token="oai-tok",
        )

        call_args = mock_client.return_value.__aenter__.return_value.post.call_args
        payload = call_args[1]["json"]
        assert payload["threadId"] == "thread-1"
        assert payload["openaiVaultToken"] == "oai-tok"


@pytest.mark.asyncio
async def test_request_embedding_processing_omits_optional_fields_when_absent():
    svc = MLService()
    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.post.return_value = _ok_response()

        await svc.request_embedding_processing(
            vault_unique_ids=["v1"], user_id="u1", company_id="c1", channel_id="ch1"
        )

        call_args = mock_client.return_value.__aenter__.return_value.post.call_args
        payload = call_args[1]["json"]
        assert "threadId" not in payload
        assert "tableName" not in payload
        assert "tableNames" not in payload
        assert "openaiVaultToken" not in payload


@pytest.mark.asyncio
async def test_request_embedding_processing_json_decode_error_branch():
    svc = MLService()
    with patch("httpx.AsyncClient") as mock_client:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = json.JSONDecodeError("bad", "doc", 0)
        mock_response.text = "not json"
        mock_response.headers = {}
        mock_client.return_value.__aenter__.return_value.post.return_value = mock_response

        result = await svc.request_embedding_processing(
            vault_unique_ids=["v1"], user_id="u1", company_id="c1", channel_id="ch1"
        )

    assert result["success"] is False
    assert result["message"] == "Invalid JSON response from ML API"


@pytest.mark.asyncio
async def test_request_embedding_processing_generic_exception_branch():
    svc = MLService()
    with patch("httpx.AsyncClient", side_effect=RuntimeError("unexpected boom")):
        result = await svc.request_embedding_processing(
            vault_unique_ids=["v1"], user_id="u1", company_id="c1", channel_id="ch1"
        )

    assert result["success"] is False
    assert result["message"] == "Unexpected error occurred"
    assert result["error"] == "unexpected boom"


# ---------------------------------------------------------------------------
# check_embedding_status
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_check_embedding_status_success():
    svc = MLService()
    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get.return_value = _ok_response(
            {"status": "processing"}
        )

        result = await svc.check_embedding_status(vault_unique_ids=["v1", "v2"])

        call_args = mock_client.return_value.__aenter__.return_value.get.call_args
        assert call_args[1]["params"] == {"vault_unique_ids": ["v1", "v2"]}
        assert result["success"] is True
        assert result["data"] == {"status": "processing"}


@pytest.mark.asyncio
async def test_check_embedding_status_uses_ml_api_key_when_no_jwt():
    svc = MLService()
    svc.ml_api_key = "service-key"
    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get.return_value = _ok_response()
        await svc.check_embedding_status(vault_unique_ids=["v1"])

        call_args = mock_client.return_value.__aenter__.return_value.get.call_args
        assert call_args[1]["headers"]["Authorization"] == "Bearer service-key"


@pytest.mark.asyncio
async def test_check_embedding_status_jwt_token_overrides_api_key():
    svc = MLService()
    svc.ml_api_key = "service-key"
    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get.return_value = _ok_response()
        await svc.check_embedding_status(vault_unique_ids=["v1"], jwt_token="jwt-abc")

        call_args = mock_client.return_value.__aenter__.return_value.get.call_args
        assert call_args[1]["headers"]["Authorization"] == "Bearer jwt-abc"


@pytest.mark.asyncio
async def test_check_embedding_status_api_error():
    svc = MLService()
    with patch("httpx.AsyncClient") as mock_client:
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "server error"
        mock_response.headers = {}
        mock_client.return_value.__aenter__.return_value.get.return_value = mock_response

        result = await svc.check_embedding_status(vault_unique_ids=["v1"])

    assert result["success"] is False
    assert "ML API error: 500" in result["message"]


@pytest.mark.asyncio
async def test_check_embedding_status_json_decode_error():
    svc = MLService()
    with patch("httpx.AsyncClient") as mock_client:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = json.JSONDecodeError("bad", "doc", 0)
        mock_response.text = "not json"
        mock_response.headers = {}
        mock_client.return_value.__aenter__.return_value.get.return_value = mock_response

        result = await svc.check_embedding_status(vault_unique_ids=["v1"])

    assert result["success"] is False
    assert result["message"] == "Invalid JSON response from ML API"


@pytest.mark.asyncio
async def test_check_embedding_status_generic_exception():
    svc = MLService()
    with patch("httpx.AsyncClient", side_effect=RuntimeError("boom")):
        result = await svc.check_embedding_status(vault_unique_ids=["v1"])

    assert result["success"] is False
    assert result["message"] == "Failed to check embedding status"
    assert result["error"] == "boom"


# ---------------------------------------------------------------------------
# delete_embeddings
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_delete_embeddings_success_with_tokens():
    svc = MLService()
    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.post.return_value = _ok_response(
            {"deleted": True}
        )

        result = await svc.delete_embeddings(
            channel_id="ch1", data_sources_vault_tokens=["v1", "v2"], embedding_type="tabular"
        )

        call_args = mock_client.return_value.__aenter__.return_value.post.call_args
        payload = call_args[1]["json"]
        assert payload["channelId"] == "ch1"
        assert payload["dataSourcesVaultTokens"] == ["v1", "v2"]
        assert payload["embeddingType"] == "tabular"
        assert result["success"] is True


@pytest.mark.asyncio
async def test_delete_embeddings_no_tokens_sends_none():
    svc = MLService()
    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.post.return_value = _ok_response()

        await svc.delete_embeddings(channel_id="ch1")

        call_args = mock_client.return_value.__aenter__.return_value.post.call_args
        payload = call_args[1]["json"]
        assert payload["dataSourcesVaultTokens"] is None
        assert payload["embeddingType"] == "textual"


@pytest.mark.asyncio
async def test_delete_embeddings_api_error():
    svc = MLService()
    with patch("httpx.AsyncClient") as mock_client:
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.text = "not found"
        mock_response.headers = {}
        mock_client.return_value.__aenter__.return_value.post.return_value = mock_response

        result = await svc.delete_embeddings(channel_id="ch1")

    assert result["success"] is False
    assert "ML API error: 404" in result["message"]


@pytest.mark.asyncio
async def test_delete_embeddings_json_decode_error():
    svc = MLService()
    with patch("httpx.AsyncClient") as mock_client:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = json.JSONDecodeError("bad", "doc", 0)
        mock_response.text = "not json"
        mock_response.headers = {}
        mock_client.return_value.__aenter__.return_value.post.return_value = mock_response

        result = await svc.delete_embeddings(channel_id="ch1")

    assert result["success"] is False
    assert result["message"] == "Invalid JSON response from ML API"


@pytest.mark.asyncio
async def test_delete_embeddings_timeout():
    svc = MLService()
    with patch("httpx.AsyncClient") as mock_client:
        from httpx import TimeoutException

        mock_client.return_value.__aenter__.return_value.post.side_effect = TimeoutException(
            "timed out"
        )
        result = await svc.delete_embeddings(channel_id="ch1")

    assert result["success"] is False
    assert result["message"] == "Timeout while calling ML API"


@pytest.mark.asyncio
async def test_delete_embeddings_connection_error():
    svc = MLService()
    with patch("httpx.AsyncClient") as mock_client:
        from httpx import RequestError

        mock_client.return_value.__aenter__.return_value.post.side_effect = RequestError(
            "connection failed"
        )
        result = await svc.delete_embeddings(channel_id="ch1")

    assert result["success"] is False
    assert result["message"] == "Failed to connect to ML API"


@pytest.mark.asyncio
async def test_delete_embeddings_generic_exception():
    svc = MLService()
    with patch("httpx.AsyncClient", side_effect=RuntimeError("boom")):
        result = await svc.delete_embeddings(channel_id="ch1")

    assert result["success"] is False
    assert result["message"] == "Unexpected error occurred"
    assert result["error"] == "boom"
