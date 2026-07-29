"""
Tests for the additive Aryx integration in datasources.py:
- upload_files_bulk(kind="aryx") starts Aryx ingestion alongside the
  existing storage upload, without changing behavior when kind is omitted.
- _aryx_ingestion_status_for() merges live Aryx job status into responses
  for datasources whose metadata carries an aryx.discovery_id.

All tests are pure-unit: no real DB, no real HTTP to Aryx.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient


def _run(coro):
    """This suite's pytest has no asyncio/anyio test-runner plugin installed
    (matches test_aryx_bridge.py, which tests async routes only via
    TestClient) — drive bare coroutines directly instead of async def tests."""
    return asyncio.run(coro)


def _make_client(mock_db):
    from app.core.database import get_db
    from app.routes.datasources import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/datasources")
    app.dependency_overrides[get_db] = lambda: mock_db
    return TestClient(app, raise_server_exceptions=False)


def _mock_company():
    company = MagicMock()
    company.id = "company-001"
    company.name = "Test Company"
    return company


def _mock_storage_service():
    svc = MagicMock()
    svc.upload_file = AsyncMock(return_value={
        "storage_path": "datasource/2026-01-01/x.csv",
        "file_url": "https://storage.example.com/x.csv",
        "provider": "s3",
    })
    return svc


# ---------------------------------------------------------------------------
# _aryx_ingestion_status_for — pure unit tests, no DB/HTTP mocking needed
# ---------------------------------------------------------------------------

class TestAryxIngestionStatusHelper:
    def test_returns_none_when_metadata_is_empty(self):
        from app.routes.datasources import _aryx_ingestion_status_for
        assert _run(_aryx_ingestion_status_for(None)) is None
        assert _run(_aryx_ingestion_status_for({})) is None

    def test_returns_none_when_no_aryx_key(self):
        from app.routes.datasources import _aryx_ingestion_status_for
        assert _run(_aryx_ingestion_status_for({"vault_unique_id": "abc"})) is None

    def test_returns_none_when_aryx_key_has_no_discovery_id(self):
        from app.routes.datasources import _aryx_ingestion_status_for
        assert _run(_aryx_ingestion_status_for({"aryx": {"kind": "aryx"}})) is None

    def test_fetches_live_status_when_discovery_id_present(self):
        from app.routes.datasources import _aryx_ingestion_status_for
        fake_status = {"status": "running", "stage": "Reading", "pct": 64}
        with patch("app.routes.datasources.call_aryx_job_status",
                   new=AsyncMock(return_value=fake_status)) as mock_call:
            result = _run(_aryx_ingestion_status_for({"aryx": {"discovery_id": "disc-123"}}))
        assert result == fake_status
        mock_call.assert_awaited_once_with("disc-123")

    def test_degrades_gracefully_when_aryx_unreachable(self):
        from app.routes.datasources import _aryx_ingestion_status_for
        with patch("app.routes.datasources.call_aryx_job_status",
                   new=AsyncMock(side_effect=HTTPException(502, "Aryx unreachable"))):
            result = _run(_aryx_ingestion_status_for({"aryx": {"discovery_id": "disc-123"}}))
        assert result == {"error": "status temporarily unavailable"}


# ---------------------------------------------------------------------------
# upload_files_bulk — regression guard + new kind="aryx" behavior
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_upload_bulk_without_kind_is_unaffected(mock_db, admin_user):
    """Regression guard: omitting kind must produce EXACTLY the prior shape —
    no aryx_ingestion key anywhere in the response."""
    mock_db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=_mock_company())))
    client = _make_client(mock_db)

    with patch("app.routes.datasources.get_current_user_required", new=AsyncMock(return_value=admin_user)), \
         patch("app.routes.datasources.get_file_storage_service", return_value=_mock_storage_service()), \
         patch("app.routes.datasources.validate_file_content", return_value=True):
        response = client.post(
            "/api/v1/datasources/upload/bulk",
            files={"files": ("report.csv", b"a,b\n1,2\n", "text/csv")},
            headers={"Authorization": "Bearer test-token"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["total_uploaded"] == 1
    assert "aryx_ingestion" not in body["uploaded_files"][0] or body["uploaded_files"][0]["aryx_ingestion"] is None


@pytest.mark.unit
def test_upload_bulk_with_kind_aryx_starts_ingestion(mock_db, admin_user):
    mock_db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=_mock_company())))
    client = _make_client(mock_db)
    mock_workspace = MagicMock()
    mock_workspace.id = "550e8400-e29b-41d4-a716-446655440000"

    with patch("app.routes.datasources.get_current_user_required", new=AsyncMock(return_value=admin_user)), \
         patch("app.routes.datasources.get_file_storage_service", return_value=_mock_storage_service()), \
         patch("app.routes.datasources.validate_file_content", return_value=True), \
         patch("app.routes.datasources._get_workspace_or_404", new=AsyncMock(return_value=mock_workspace)), \
         patch("app.routes.datasources.require_active_workspace_role", new=AsyncMock(return_value="admin")), \
         patch("app.routes.datasources._resolve_aryx_workspace_id_for_datasources", new=AsyncMock(return_value=10)), \
         patch("app.routes.datasources.call_aryx_docs_read",
               new=AsyncMock(return_value={"discovery_id": "disc-abc"})) as mock_read:
        response = client.post(
            "/api/v1/datasources/upload/bulk",
            files={"files": ("report.csv", b"a,b\n1,2\n", "text/csv")},
            data={"kind": "aryx", "workspace_id": "550e8400-e29b-41d4-a716-446655440000"},
            headers={"Authorization": "Bearer test-token"},
        )

    assert response.status_code == 200
    body = response.json()
    entry = body["uploaded_files"][0]
    assert entry["aryx_ingestion"] == {"discovery_id": "disc-abc", "status": "queued"}
    # Existing storage-upload fields must be completely unaffected.
    assert entry["storage_path"] == "datasource/2026-01-01/x.csv"
    mock_read.assert_awaited_once()
    args, _ = mock_read.call_args
    assert args[0] == 10  # resolved aryx_workspace_id


@pytest.mark.unit
def test_upload_bulk_kind_aryx_without_workspace_id_fails_gracefully_per_file(mock_db, admin_user):
    """kind='aryx' with no workspace_id must NOT fail the upload itself —
    only that file's aryx_ingestion becomes an error."""
    mock_db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=_mock_company())))
    client = _make_client(mock_db)

    with patch("app.routes.datasources.get_current_user_required", new=AsyncMock(return_value=admin_user)), \
         patch("app.routes.datasources.get_file_storage_service", return_value=_mock_storage_service()), \
         patch("app.routes.datasources.validate_file_content", return_value=True):
        response = client.post(
            "/api/v1/datasources/upload/bulk",
            files={"files": ("report.csv", b"a,b\n1,2\n", "text/csv")},
            data={"kind": "aryx"},
            headers={"Authorization": "Bearer test-token"},
        )

    assert response.status_code == 200
    body = response.json()
    entry = body["uploaded_files"][0]
    assert entry["aryx_ingestion"]["error"] == "workspace_id is required when kind='aryx'"
    assert body["total_uploaded"] == 1  # the storage upload itself still succeeded
