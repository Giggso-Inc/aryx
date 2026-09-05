"""
Golden-master / characterization tests for app/routes/datasources.py.

Purpose: this file is the single largest file in the codebase (5,517 lines,
24 endpoints) and is about to be split into smaller modules (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5). Before the split,
we capture the CURRENT observable behavior of every endpoint that previously
had zero test coverage, so the split can be verified to change nothing.

These are characterization tests, not "correctness" tests: assertions match
what the code actually does today, bugs included. Where the code has a
pre-existing defect (e.g. update_datasource's response model is missing two
required fields, or bulk_manage_datasource_connections' own "invalid action"
branch is unreachable because FastAPI's own pydantic validation on the
request body already rejects the value first), the test documents that
defect rather than "fixing" the assertion to what would be sensible.

Pattern follows tests/test_datasources_aryx_integration.py exactly:
- FastAPI TestClient with `app.include_router(router, prefix=...)`.
- `app.dependency_overrides[get_db] = lambda: mock_db`.
- MagicMock/AsyncMock for services; no real DB, no real HTTP.
- `_run()` + asyncio.run() instead of pytest-asyncio (no async plugin
  installed in this suite).

Do not modify app/routes/datasources.py from this file's tests.
"""

from __future__ import annotations

import asyncio
import io
import json
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _run(coro):
    return asyncio.run(coro)


def _make_client(mock_db):
    from app.core.database import get_db
    from app.routes.datasources import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/datasources")
    app.dependency_overrides[get_db] = lambda: mock_db
    return TestClient(app, raise_server_exceptions=False)


AUTH_HEADERS = {"Authorization": "Bearer test-token"}


# ---------------------------------------------------------------------------
# Shared fake result / mock helpers
# ---------------------------------------------------------------------------

class _FakeResult:
    """Mimics the subset of SQLAlchemy's async Result API this file's
    endpoints actually call: .scalar_one_or_none(), .scalars().all()/.first(),
    .scalar(), and plain iteration (used for grouped-count queries)."""

    def __init__(self, scalar_one_or_none=None, all_=None, scalar_val=None, rows=None):
        self._son = scalar_one_or_none
        self._all = all_ if all_ is not None else []
        self._scalar_val = scalar_val
        self._rows = rows if rows is not None else []

    def scalar_one_or_none(self):
        return self._son

    def scalars(self):
        m = MagicMock()
        m.all = MagicMock(return_value=self._all)
        m.first = MagicMock(return_value=self._all[0] if self._all else None)
        return m

    def scalar(self):
        return self._scalar_val

    def __iter__(self):
        return iter(self._rows)


def _exec_seq(*results):
    """db.execute side_effect list — one _FakeResult (or MagicMock) per
    expected call, in call order."""
    return AsyncMock(side_effect=list(results))


def _simulate_refresh(obj):
    """Fills in the column defaults that a real DB would apply on INSERT
    (is_active=True, processing_status='pending', created_at=now(), ...).
    Our mock_db.refresh() is a bare AsyncMock no-op, so without this the
    freshly-constructed Datasource ORM object would have these attributes
    as None — which is not what happens against a real database (Column
    defaults are applied there). Used as `mock_db.refresh.side_effect`."""
    defaults = {
        "is_active": True,
        "is_connected": True,
        "is_processed": False,
        "processing_status": "pending",
        "record_count": 0,
        "is_embedding_required": False,
        "embedding_status": 0,
        "error_message": None,
        "last_processed_at": None,
        "processing_time": None,
    }
    for key, val in defaults.items():
        if getattr(obj, key, None) is None:
            setattr(obj, key, val)
    now = datetime.utcnow()
    if getattr(obj, "created_at", None) is None:
        obj.created_at = now
    if getattr(obj, "updated_at", None) is None:
        obj.updated_at = now


def _mock_channel(**overrides):
    ch = MagicMock()
    ch.id = uuid.uuid4()
    ch.workspace_id = uuid.uuid4()
    ch.company_id = "company-001"
    ch.is_accessible_by_user = MagicMock(return_value=True)
    for k, v in overrides.items():
        setattr(ch, k, v)
    return ch


def _mock_datasource(**overrides):
    ds = MagicMock()
    ds.id = str(uuid.uuid4())
    ds.name = "My Datasource"
    ds.filename = "file.csv"
    ds.storage_type = "local"
    ds.provider = None
    ds.app_type = None
    ds.config = {}
    ds.datasource_metadata = {}
    ds.giggso_vault_id = None
    ds.file_size = 100
    ds.file_type = "text/csv"
    ds.file_url = None
    ds.channel_id = uuid.uuid4()
    ds.added_by = "user-admin-001"
    ds.is_active = True
    ds.is_connected = True
    ds.is_processed = False
    ds.processing_status = "pending"
    ds.error_message = None
    ds.last_processed_at = None
    ds.processing_time = None
    ds.record_count = 0
    ds.is_embedding_required = False
    ds.embedding_status = 0
    ds.created_at = datetime.utcnow()
    ds.updated_at = datetime.utcnow()
    ds.is_accessible_by_user = MagicMock(return_value=True)
    for k, v in overrides.items():
        setattr(ds, k, v)
    return ds


def _company():
    c = MagicMock()
    c.id = "company-001"
    c.name = "Test Co"
    return c


def _storage_service():
    svc = MagicMock()
    svc.upload_file = AsyncMock(return_value={
        "storage_path": "ds/2026-01-01/x.csv",
        "file_url": "https://storage.example.com/x.csv",
        "provider": "local",
    })
    svc.download_file = AsyncMock(return_value=b"file-bytes")
    return svc


def _auth(user, module="crud"):
    return patch(f"app.routes.datasources.{module}.get_current_user_required", new=AsyncMock(return_value=user))


# ===========================================================================
# GET /supported-log-types
# ===========================================================================

class TestSupportedLogTypes:
    @pytest.mark.unit
    def test_returns_configured_list(self, mock_db):
        client = _make_client(mock_db)
        with patch("app.routes.datasources.misc.settings.SUPPORTED_LOG_TYPES", ["android", "python"]):
            resp = client.get("/api/v1/datasources/supported-log-types")
        assert resp.status_code == 200
        assert resp.json() == ["android", "python"]


# ===========================================================================
# GET /environment
# ===========================================================================

class TestEnvironmentConfig:
    @pytest.mark.unit
    def test_returns_environment_info(self, mock_db):
        client = _make_client(mock_db)
        with patch("app.services.vault_data_builder.get_environment_info",
                   return_value={"vault_mode": "test"}):
            resp = client.get("/api/v1/datasources/environment")
        assert resp.status_code == 200
        assert resp.json() == {"vault_mode": "test"}


# ===========================================================================
# POST / — create_datasource
# ===========================================================================

class TestCreateDatasource:
    def _payload(self, **overrides):
        payload = {
            "name": "My DS",
            "filename": "file.csv",
            "storage_type": "local",
            "channel_id": str(uuid.uuid4()),
            "file_size": 10,
            "file_type": "text/csv",
        }
        payload.update(overrides)
        return payload

    @pytest.mark.unit
    def test_channel_not_found_returns_404(self, mock_db, admin_user):
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        client = _make_client(mock_db)
        with _auth(admin_user, "create"):
            resp = client.post("/api/v1/datasources/", json=self._payload(), headers=AUTH_HEADERS)
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Channel not found"

    @pytest.mark.unit
    def test_duplicate_name_in_channel_returns_409(self, mock_db, admin_user):
        channel = _mock_channel()
        existing = _mock_datasource()
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=channel),
            _FakeResult(all_=[existing]),
        )
        client = _make_client(mock_db)
        with _auth(admin_user, "create"):
            resp = client.post("/api/v1/datasources/", json=self._payload(), headers=AUTH_HEADERS)
        assert resp.status_code == 409
        assert "already exists in this channel" in resp.json()["detail"]

    @pytest.mark.unit
    def test_cloud_storage_without_provider_returns_400(self, mock_db, admin_user):
        channel = _mock_channel()
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=channel),
            _FakeResult(all_=[]),
        )
        client = _make_client(mock_db)
        payload = self._payload(storage_type="cloud", filename="x.csv")
        with _auth(admin_user, "create"):
            resp = client.post("/api/v1/datasources/", json=payload, headers=AUTH_HEADERS)
        assert resp.status_code == 400
        assert resp.json()["detail"] == "Provider is required for cloud storage type"

    @pytest.mark.unit
    def test_local_storage_happy_path(self, mock_db, admin_user):
        channel = _mock_channel()
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=channel),
            _FakeResult(all_=[]),
        )
        mock_db.refresh = AsyncMock(side_effect=_simulate_refresh)
        client = _make_client(mock_db)
        with _auth(admin_user, "create"), \
             patch("app.routes.datasources._create_persist.handle_vault_integration", new=AsyncMock(return_value=None)):
            resp = client.post("/api/v1/datasources/", json=self._payload(), headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "My DS"
        assert body["storage_type"] == "local"
        assert body["giggso_vault_id"] is None
        assert body["is_active"] is True


# ===========================================================================
# POST /upload — upload_file
# ===========================================================================

class TestUploadFile:
    @pytest.mark.unit
    def test_company_not_found_returns_404(self, mock_db, admin_user):
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        client = _make_client(mock_db)
        with _auth(admin_user, "upload_single"):
            resp = client.post(
                "/api/v1/datasources/upload",
                files={"file": ("a.csv", b"a,b\n1,2\n", "text/csv")},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Company not found"

    @pytest.mark.unit
    def test_happy_path_returns_upload_metadata(self, mock_db, admin_user):
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=_company()))
        client = _make_client(mock_db)
        with _auth(admin_user, "upload_single"), \
             patch("app.routes.datasources.upload_single.get_file_storage_service", return_value=_storage_service()), \
             patch("app.routes.datasources.upload_single.validate_file_content", return_value=True):
            resp = client.post(
                "/api/v1/datasources/upload",
                files={"file": ("a.csv", b"a,b\n1,2\n", "text/csv")},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["filename"] == "a.csv"
        assert body["storage_path"] == "ds/2026-01-01/x.csv"
        assert body["provider"] == "local"

    @pytest.mark.unit
    def test_validation_failure_returns_500(self, mock_db, admin_user):
        """Current behavior: validate_file_content raising False triggers the
        function's own HTTPException(400), but that HTTPException is raised
        INSIDE the try/except Exception block below it, which re-wraps it
        as a 500 — the endpoint has no `except HTTPException: raise` guard
        (unlike several other endpoints in this file)."""
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=_company()))
        client = _make_client(mock_db)
        with _auth(admin_user, "upload_single"), \
             patch("app.routes.datasources.upload_single.get_file_storage_service", return_value=_storage_service()), \
             patch("app.routes.datasources.upload_single.validate_file_content", return_value=False):
            resp = client.post(
                "/api/v1/datasources/upload",
                files={"file": ("a.csv", b"a,b\n1,2\n", "text/csv")},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 500
        assert "Failed to upload file" in resp.json()["detail"]


# ===========================================================================
# POST /from-upload — create_datasource_from_upload
# ===========================================================================

class TestCreateDatasourceFromUpload:
    @pytest.mark.unit
    def test_invalid_metadata_json_returns_400(self, mock_db, admin_user):
        client = _make_client(mock_db)
        with _auth(admin_user, "from_upload"):
            resp = client.post(
                "/api/v1/datasources/from-upload",
                data={"channel_id": str(uuid.uuid4()), "datasource_metadata": "{not json"},
                files={"file": ("a.csv", b"1,2\n", "text/csv")},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 400
        assert resp.json()["detail"] == "Invalid JSON in datasource_metadata"

    @pytest.mark.unit
    def test_channel_not_found_returns_404(self, mock_db, admin_user):
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        client = _make_client(mock_db)
        with _auth(admin_user, "from_upload"):
            resp = client.post(
                "/api/v1/datasources/from-upload",
                data={"channel_id": str(uuid.uuid4())},
                files={"file": ("a.csv", b"1,2\n", "text/csv")},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Channel not found"


# ===========================================================================
# POST /from-upload/bulk — create_datasources_from_upload_bulk
# ===========================================================================

class TestCreateDatasourcesFromUploadBulk:
    @pytest.mark.unit
    def test_unusable_via_multipart_returns_422(self, mock_db, admin_user):
        """Pre-existing bug, unrelated to this characterization effort: the
        handler declares `datasources_data: DatasourceFromUploadBulk` as a
        plain (non-Form) pydantic-model parameter alongside `files: List[
        UploadFile] = File(...)`. FastAPI cannot parse a nested JSON body
        field out of a multipart/form-data request this way — passing it
        as a top-level form field (even JSON-encoded) fails validation with
        'Input should be a valid dictionary', and omitting it entirely fails
        with 'Field required'. Net effect: this endpoint 422s for every
        request that also includes files (which is every real caller — files
        are required), so the endpoint's own file/datasource-count-mismatch
        400 check below is unreachable in practice."""
        client = _make_client(mock_db)
        payload = {"datasources": [{"channel_id": str(uuid.uuid4())}]}
        with _auth(admin_user, "from_upload_bulk"):
            resp = client.post(
                "/api/v1/datasources/from-upload/bulk",
                data={"datasources_data": json.dumps(payload)},
                files=[
                    ("files", ("a.csv", b"1,2\n", "text/csv")),
                    ("files", ("b.csv", b"3,4\n", "text/csv")),
                ],
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 422
        assert resp.json()["detail"][0]["loc"] == ["body", "datasources_data"]

    @pytest.mark.unit
    def test_missing_datasources_data_also_returns_422(self, mock_db, admin_user):
        client = _make_client(mock_db)
        with _auth(admin_user, "from_upload_bulk"):
            resp = client.post(
                "/api/v1/datasources/from-upload/bulk",
                files=[("files", ("a.csv", b"1,2\n", "text/csv"))],
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 422
        assert resp.json()["detail"][0]["msg"] == "Field required"


# ===========================================================================
# POST /bulk — create_datasources_bulk
# ===========================================================================

class TestCreateDatasourcesBulk:
    @pytest.mark.unit
    def test_channel_not_found_is_reported_as_failed_not_500(self, mock_db, admin_user):
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        client = _make_client(mock_db)
        payload = {"datasources": [{
            "name": "DS1",
            "filename": "a.csv",
            "storage_type": "local",
            "channel_id": str(uuid.uuid4()),
        }]}
        with _auth(admin_user, "bulk_create"):
            resp = client.post("/api/v1/datasources/bulk", json=payload, headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_created"] == 0
        assert body["total_failed"] == 1
        assert body["failed_datasources"][0]["error"] == "Channel not found"


# ===========================================================================
# POST /internal/bulk — create_datasources_bulk_internal
# ===========================================================================

class TestCreateDatasourcesBulkInternal:
    @pytest.mark.unit
    def test_missing_api_key_returns_401(self, mock_db):
        client = _make_client(mock_db)
        resp = client.post(
            "/api/v1/datasources/internal/bulk",
            json={"datasources": [{
                "name": "DS1", "storage_type": "local", "filename": "a.csv",
                "thread_id": str(uuid.uuid4()),
            }]},
        )
        assert resp.status_code == 401
        assert "API key is required" in resp.json()["detail"]

    @pytest.mark.unit
    def test_invalid_api_key_returns_401(self, mock_db):
        client = _make_client(mock_db)
        with patch("app.routes.datasources._bulk_internal_auth.settings.ML_API_KEY", "expected-key"):
            resp = client.post(
                "/api/v1/datasources/internal/bulk",
                json={"datasources": [{
                    "name": "DS1", "storage_type": "local", "filename": "a.csv",
                    "thread_id": str(uuid.uuid4()),
                }]},
                headers={"X-API-Key": "wrong-key"},
            )
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid API key"

    @pytest.mark.unit
    def test_unconfigured_api_key_returns_500(self, mock_db):
        """Current behavior: an empty/unset ML_API_KEY setting turns even a
        correctly-supplied X-API-Key header into a 500, not a 401 — the
        'not configured' check runs before the equality check."""
        client = _make_client(mock_db)
        with patch("app.routes.datasources._bulk_internal_auth.settings.ML_API_KEY", ""):
            resp = client.post(
                "/api/v1/datasources/internal/bulk",
                json={"datasources": [{
                    "name": "DS1", "storage_type": "local", "filename": "a.csv",
                    "thread_id": str(uuid.uuid4()),
                }]},
                headers={"X-API-Key": "anything"},
            )
        assert resp.status_code == 500
        assert "not configured" in resp.json()["detail"]


# ===========================================================================
# GET / — list_datasources
# ===========================================================================

class TestListDatasources:
    @pytest.mark.unit
    def test_happy_path_empty_list(self, mock_db, admin_user):
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_val=0),   # count query
            _FakeResult(all_=[]),        # main query
        )
        client = _make_client(mock_db)
        with _auth(admin_user, "list_datasources"):
            resp = client.get("/api/v1/datasources/", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["datasources"] == []
        assert body["total"] == 0
        assert body["page"] == 1
        assert body["pages"] == 0

    @pytest.mark.unit
    def test_invalid_channel_id_format_returns_400(self, mock_db, admin_user):
        client = _make_client(mock_db)
        with _auth(admin_user, "list_datasources"), \
             patch("app.routes.datasources.list_datasources.check_channel_access", new=AsyncMock(return_value=True)):
            resp = client.get("/api/v1/datasources/", params={"channel_id": "not-a-uuid"}, headers=AUTH_HEADERS)
        assert resp.status_code == 400
        assert "Invalid channel_id format" in resp.json()["detail"]


# ===========================================================================
# GET /stats — get_datasource_stats
# ===========================================================================

class TestDatasourceStats:
    @pytest.mark.unit
    def test_happy_path(self, mock_db, admin_user):
        ds_active = _mock_datasource(file_size=50)
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_val=3),          # total
            _FakeResult(all_=[ds_active]),      # active
            _FakeResult(all_=[]),               # processed
            _FakeResult(all_=[]),               # pending
            _FakeResult(all_=[]),               # failed
            _FakeResult(all_=[ds_active]),      # with size
            _FakeResult(rows=[]),               # storage type breakdown
            _FakeResult(all_=[]),               # provider breakdown
        )
        client = _make_client(mock_db)
        with _auth(admin_user, "stats_count"):
            resp = client.get("/api/v1/datasources/stats", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_datasources"] == 3
        assert body["active_datasources"] == 1
        assert body["total_file_size"] == 50


# ===========================================================================
# GET /count — get_datasource_type_count
# ===========================================================================

class TestDatasourceTypeCount:
    @pytest.mark.unit
    def test_happy_path(self, mock_db, admin_user):
        Row = MagicMock()
        Row.storage_type = "local"
        Row.count = 2
        mock_db.execute = _exec_seq(_FakeResult(rows=[Row]))
        client = _make_client(mock_db)
        with _auth(admin_user, "stats_count"):
            resp = client.get("/api/v1/datasources/count", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_connected"] == 2
        by_type = {c["type"]: c["count"] for c in body["counts"]}
        assert by_type["local"] == 2
        assert by_type["cloud"] == 0


# ===========================================================================
# GET /{id} — get_datasource
# ===========================================================================

class TestGetDatasource:
    @pytest.mark.unit
    def test_not_found_returns_404(self, mock_db, admin_user):
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        client = _make_client(mock_db)
        with _auth(admin_user, "get_datasource"):
            resp = client.get(f"/api/v1/datasources/{uuid.uuid4()}", headers=AUTH_HEADERS)
        assert resp.status_code == 404

    @pytest.mark.unit
    def test_happy_path_has_null_aryx_status(self, mock_db, admin_user):
        ds = _mock_datasource()
        channel = _mock_channel()
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=ds),
            _FakeResult(scalar_one_or_none=channel),
        )
        client = _make_client(mock_db)
        with _auth(admin_user, "get_datasource"):
            resp = client.get(f"/api/v1/datasources/{ds.id}", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == ds.id
        assert body["aryx_ingestion_status"] is None


# ===========================================================================
# GET /{id}/download — download_datasource
# ===========================================================================

class TestDownloadDatasource:
    @pytest.mark.unit
    def test_not_found_returns_404(self, mock_db, admin_user):
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        client = _make_client(mock_db)
        with _auth(admin_user, "download_datasource"):
            resp = client.get(f"/api/v1/datasources/{uuid.uuid4()}/download", headers=AUTH_HEADERS)
        assert resp.status_code == 404

    @pytest.mark.unit
    def test_database_storage_type_returns_404_with_explanation(self, mock_db, admin_user):
        ds = _mock_datasource(storage_type="database", provider="mysql", config={}, file_url=None)
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=ds))
        client = _make_client(mock_db)
        with _auth(admin_user, "download_datasource"), \
             patch("app.routes.datasources.download_datasource.get_storage_file_path_for_deletion", return_value=None), \
             patch("app.routes.datasources.download_datasource.get_external_view_url_for_datasource", return_value=None):
            resp = client.get(f"/api/v1/datasources/{ds.id}/download", headers=AUTH_HEADERS)
        assert resp.status_code == 404
        assert "do not have a viewable or downloadable file" in resp.json()["detail"]

    @pytest.mark.unit
    def test_no_file_available_returns_generic_404(self, mock_db, admin_user):
        ds = _mock_datasource(storage_type="local", config={}, file_url=None)
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=ds))
        client = _make_client(mock_db)
        with _auth(admin_user, "download_datasource"), \
             patch("app.routes.datasources.download_datasource.get_storage_file_path_for_deletion", return_value=None), \
             patch("app.routes.datasources.download_datasource.get_external_view_url_for_datasource", return_value=None):
            resp = client.get(f"/api/v1/datasources/{ds.id}/download", headers=AUTH_HEADERS)
        assert resp.status_code == 404
        assert resp.json()["detail"] == "No downloadable file found for this datasource"

    @pytest.mark.unit
    def test_stored_file_streams_with_attachment_disposition(self, mock_db, admin_user):
        ds = _mock_datasource(storage_type="local", filename="report.csv")
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=ds))
        client = _make_client(mock_db)
        with _auth(admin_user, "download_datasource"), \
             patch("app.routes.datasources.download_datasource.get_storage_file_path_for_deletion", return_value="path/report.csv"), \
             patch("app.routes.datasources.download_datasource.get_file_storage_service", return_value=_storage_service()):
            resp = client.get(f"/api/v1/datasources/{ds.id}/download", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        assert resp.content == b"file-bytes"
        assert 'attachment; filename="report.csv"' in resp.headers["content-disposition"]


# ===========================================================================
# PUT /{id} — update_datasource
# ===========================================================================

class TestUpdateDatasource:
    @pytest.mark.unit
    def test_not_found_returns_404(self, mock_db, admin_user):
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        client = _make_client(mock_db)
        with _auth(admin_user, "update"):
            resp = client.put(f"/api/v1/datasources/{uuid.uuid4()}", json={"name": "New"}, headers=AUTH_HEADERS)
        assert resp.status_code == 404

    @pytest.mark.unit
    def test_current_behavior_500_missing_response_fields(self, mock_db, admin_user):
        """Pre-existing bug, unrelated to this characterization effort: the
        DatasourceResponse built here omits `is_embedding_required` and
        `embedding_status`, both required (non-Optional, no default) fields
        on the schema. Every call to this endpoint currently 500s — even a
        perfectly valid update of an accessible, existing datasource."""
        ds = _mock_datasource()
        channel = _mock_channel()
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=ds),
            _FakeResult(scalar_one_or_none=channel),
        )
        client = _make_client(mock_db)
        with _auth(admin_user, "update"):
            resp = client.put(f"/api/v1/datasources/{ds.id}", json={"name": "New Name"}, headers=AUTH_HEADERS)
        assert resp.status_code == 500


# ===========================================================================
# DELETE /{id} — delete_datasource
# ===========================================================================

class TestDeleteDatasource:
    @pytest.mark.unit
    def test_not_found_returns_404(self, mock_db, admin_user):
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        client = _make_client(mock_db)
        with _auth(admin_user, "delete"):
            resp = client.delete(f"/api/v1/datasources/{uuid.uuid4()}", headers=AUTH_HEADERS)
        assert resp.status_code == 404

    @pytest.mark.unit
    def test_happy_path_no_embedding_required(self, mock_db, admin_user):
        ds = _mock_datasource(is_embedding_required=False, giggso_vault_id=None)
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=ds))
        mock_db.delete = AsyncMock()
        client = _make_client(mock_db)
        with _auth(admin_user, "delete"):
            resp = client.delete(f"/api/v1/datasources/{ds.id}", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        assert resp.json() == {"message": "Datasource deleted successfully"}
        mock_db.delete.assert_awaited_once_with(ds)


# ===========================================================================
# POST /process — process_datasources
# ===========================================================================

class TestProcessDatasources:
    @pytest.mark.unit
    def test_valid_request_body_500s_on_schema_code_mismatch(self, mock_db, admin_user):
        """Pre-existing bug, unrelated to this characterization effort:
        DatasourceProcessingRequest declares `datasource_ids` (a list, per
        the schema), but the handler body reads `processing_request.
        datasource_id` (singular — an attribute that does not exist on the
        model). Any request satisfying the schema's actual required field
        therefore 500s inside the handler with an AttributeError, even
        though FastAPI's own request validation passes."""
        client = _make_client(mock_db)
        with _auth(admin_user, "process_datasource"):
            resp = client.post(
                "/api/v1/datasources/process",
                json={"datasource_ids": [str(uuid.uuid4())]},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 500

    @pytest.mark.unit
    def test_wrong_field_name_in_body_returns_422(self, mock_db, admin_user):
        """A caller using the (non-existent, handler-only) singular field
        name `datasource_id` fails FastAPI's own request validation before
        ever reaching the handler, since the schema requires `datasource_ids`."""
        client = _make_client(mock_db)
        with _auth(admin_user, "process_datasource"):
            resp = client.post(
                "/api/v1/datasources/process",
                json={"datasource_id": str(uuid.uuid4())},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 422


# ===========================================================================
# POST /bulk-connection — bulk_manage_datasource_connections
# ===========================================================================

class TestBulkManageDatasourceConnections:
    @pytest.mark.unit
    def test_invalid_action_rejected_by_pydantic_not_endpoint_code(self, mock_db, admin_user):
        """Current behavior: DatasourceConnectionRequest.action already has
        pattern='^(connect|disconnect)$', so FastAPI's request-body
        validation rejects an invalid action with 422 before the endpoint's
        own `if action not in [...]: raise HTTPException(400, ...)` check
        ever runs — that check is dead code for this field."""
        client = _make_client(mock_db)
        with _auth(admin_user, "bulk_connection"):
            resp = client.post(
                "/api/v1/datasources/bulk-connection",
                json={"datasource_ids": [str(uuid.uuid4())], "action": "toggle"},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 422

    @pytest.mark.unit
    def test_missing_datasources_returns_404(self, mock_db, admin_user):
        mock_db.execute = _exec_seq(_FakeResult(all_=[]))
        client = _make_client(mock_db)
        ds_id = str(uuid.uuid4())
        with _auth(admin_user, "bulk_connection"):
            resp = client.post(
                "/api/v1/datasources/bulk-connection",
                json={"datasource_ids": [ds_id], "action": "connect"},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 404
        assert ds_id in resp.json()["detail"]

    @pytest.mark.unit
    def test_happy_path_connect(self, mock_db, admin_user):
        ds = _mock_datasource(is_connected=False)
        mock_db.execute = _exec_seq(_FakeResult(all_=[ds]))
        client = _make_client(mock_db)
        with _auth(admin_user, "bulk_connection"):
            resp = client.post(
                "/api/v1/datasources/bulk-connection",
                json={"datasource_ids": [ds.id], "action": "connect"},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_successful"] == 1
        assert body["action_performed"] == "connect"
        assert ds.is_connected is True


# ===========================================================================
# POST /{id}/connect, /{id}/disconnect — single connect/disconnect
# ===========================================================================

class TestConnectDisconnect:
    @pytest.mark.unit
    def test_connect_not_found_returns_404(self, mock_db, admin_user):
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        client = _make_client(mock_db)
        with _auth(admin_user, "connect"):
            resp = client.post(f"/api/v1/datasources/{uuid.uuid4()}/connect", headers=AUTH_HEADERS)
        assert resp.status_code == 404

    @pytest.mark.unit
    def test_connect_already_connected_returns_400(self, mock_db, admin_user):
        ds = _mock_datasource(is_connected=True)
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=ds))
        client = _make_client(mock_db)
        with _auth(admin_user, "connect"):
            resp = client.post(f"/api/v1/datasources/{ds.id}/connect", headers=AUTH_HEADERS)
        assert resp.status_code == 400
        assert resp.json()["detail"] == "Datasource is already connected"

    @pytest.mark.unit
    def test_connect_happy_path(self, mock_db, admin_user):
        ds = _mock_datasource(is_connected=False)
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=ds))
        client = _make_client(mock_db)
        with _auth(admin_user, "connect"):
            resp = client.post(f"/api/v1/datasources/{ds.id}/connect", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["is_connected"] is True
        assert body["message"] == "Datasource connected successfully"

    @pytest.mark.unit
    def test_disconnect_already_disconnected_returns_400(self, mock_db, admin_user):
        ds = _mock_datasource(is_connected=False)
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=ds))
        client = _make_client(mock_db)
        with _auth(admin_user, "disconnect"):
            resp = client.post(f"/api/v1/datasources/{ds.id}/disconnect", headers=AUTH_HEADERS)
        assert resp.status_code == 400
        assert resp.json()["detail"] == "Datasource is already disconnected"

    @pytest.mark.unit
    def test_disconnect_happy_path(self, mock_db, admin_user):
        ds = _mock_datasource(is_connected=True)
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=ds))
        client = _make_client(mock_db)
        with _auth(admin_user, "disconnect"):
            resp = client.post(f"/api/v1/datasources/{ds.id}/disconnect", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["is_connected"] is False
        assert body["message"] == "Datasource disconnected successfully"


# ===========================================================================
# GET /{id}/connection-status
# ===========================================================================

class TestConnectionStatus:
    @pytest.mark.unit
    def test_not_found_returns_404(self, mock_db, admin_user):
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        client = _make_client(mock_db)
        with _auth(admin_user, "connection_status"):
            resp = client.get(f"/api/v1/datasources/{uuid.uuid4()}/connection-status", headers=AUTH_HEADERS)
        assert resp.status_code == 404

    @pytest.mark.unit
    def test_happy_path_connected(self, mock_db, admin_user):
        ds = _mock_datasource(is_connected=True)
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=ds))
        client = _make_client(mock_db)
        with _auth(admin_user, "connection_status"):
            resp = client.get(f"/api/v1/datasources/{ds.id}/connection-status", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["message"] == "Datasource is connected"


# ===========================================================================
# GET /embedding-status/{channel_id}
# ===========================================================================

class TestEmbeddingStatusByChannel:
    @pytest.mark.unit
    def test_channel_not_found_returns_404(self, mock_db, admin_user):
        channel_id = str(uuid.uuid4())
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        client = _make_client(mock_db)
        with _auth(admin_user, "embedding_status"), \
             patch("app.routes.datasources.embedding_status.check_channel_access", new=AsyncMock(return_value=True)):
            resp = client.get(f"/api/v1/datasources/embedding-status/{channel_id}", headers=AUTH_HEADERS)
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Channel not found"

    @pytest.mark.unit
    def test_happy_path_counts_by_status(self, mock_db, admin_user):
        channel_id = str(uuid.uuid4())
        channel = _mock_channel()
        ds_done = _mock_datasource(is_embedding_required=True, embedding_status=2)
        ds_pending = _mock_datasource(is_embedding_required=True, embedding_status=1)
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=channel),
            _FakeResult(all_=[ds_done, ds_pending]),
        )
        client = _make_client(mock_db)
        with _auth(admin_user, "embedding_status"), \
             patch("app.routes.datasources.embedding_status.check_channel_access", new=AsyncMock(return_value=True)):
            resp = client.get(f"/api/v1/datasources/embedding-status/{channel_id}", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_datasources"] == 2
        assert body["completed"] == 1
        assert body["in_progress"] == 1
        assert body["embedding_required"] == 2


# ===========================================================================
# POST /embedding/webhook — ml_embedding_webhook
# ===========================================================================

class TestMlEmbeddingWebhook:
    @pytest.mark.unit
    def test_currently_a_no_op_by_design(self, mock_db):
        """Current behavior: status-update logic is commented out (see the
        TODO in the source) — the webhook always reports 0 processed / 0
        failed regardless of payload, and never touches the DB."""
        client = _make_client(mock_db)
        resp = client.post(
            "/api/v1/datasources/embedding/webhook",
            json={"vaultUniqueIds": ["abc-123"], "status": "success"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["processed_count"] == 0
        assert body["failed_count"] == 0
        assert "temporarily disabled" in body["message"]


# ===========================================================================
# POST /embedding/regenerate/{id} — regenerate_embedding
# ===========================================================================

class TestRegenerateEmbedding:
    @pytest.mark.unit
    def test_not_found_returns_404(self, mock_db, admin_user):
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        client = _make_client(mock_db)
        with _auth(admin_user, "embedding_regenerate"):
            resp = client.post(f"/api/v1/datasources/embedding/regenerate/{uuid.uuid4()}", headers=AUTH_HEADERS)
        assert resp.status_code == 404

    @pytest.mark.unit
    def test_not_owner_returns_403(self, mock_db, admin_user):
        ds = _mock_datasource(added_by="some-other-user-id")
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=ds))
        client = _make_client(mock_db)
        with _auth(admin_user, "embedding_regenerate"):
            resp = client.post(f"/api/v1/datasources/embedding/regenerate/{ds.id}", headers=AUTH_HEADERS)
        assert resp.status_code == 403
        assert "don't have permission" in resp.json()["detail"]

    @pytest.mark.unit
    def test_no_vault_integration_returns_400(self, mock_db, admin_user):
        ds = _mock_datasource(added_by=admin_user.id, giggso_vault_id=None)
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=ds))
        client = _make_client(mock_db)
        with _auth(admin_user, "embedding_regenerate"):
            resp = client.post(f"/api/v1/datasources/embedding/regenerate/{ds.id}", headers=AUTH_HEADERS)
        assert resp.status_code == 400
        assert "does not have vault integration" in resp.json()["detail"]

    @pytest.mark.unit
    def test_happy_path_initiates_regeneration(self, mock_db, admin_user):
        ds = _mock_datasource(added_by=admin_user.id, giggso_vault_id=str(uuid.uuid4()), datasource_metadata={})
        vault_record = MagicMock()
        vault_record.vault_unique_id = "vault-unique-1"
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=ds),
            _FakeResult(scalar_one_or_none=vault_record),
        )
        socket_service = MagicMock()
        socket_service.is_socket_connected = MagicMock(return_value=False)
        client = _make_client(mock_db)
        with _auth(admin_user, "embedding_regenerate"), \
             patch("app.routes.datasources.embedding_regenerate.get_completed_embeddings_by_channel", new=AsyncMock(return_value=[])), \
             patch("app.routes.datasources.embedding_regenerate.get_openai_vault_token_for_company", new=AsyncMock(return_value=None)), \
             patch("app.routes.datasources._regenerate_ml_call.extract_table_names_from_datasources", return_value=None), \
             patch("app.routes.datasources._regenerate_ml_call.ml_service.request_embedding_processing",
                   new=AsyncMock(return_value={"success": True})), \
             patch("app.routes.datasources._regenerate_ml_call.get_socket_service", return_value=socket_service):
            resp = client.post(f"/api/v1/datasources/embedding/regenerate/{ds.id}", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["embedding_status"] == 1
        assert body["status_description"] == "in_progress"
