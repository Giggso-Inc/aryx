"""
Unit tests for GGDatasource routes and schemas.
Covers all 25 endpoints in app/routes/gg_datasources.py plus the new
schema classes added to app/schemas/gg_datasource.py.
Markers:
  @pytest.mark.unit  — no real DB; run with: pytest -m unit
"""

import io
import json
import os
import sys
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://accsell_user:accsell_pass@localhost:5433/accsell_test",
)
sys.modules.setdefault("socketio", MagicMock())
sys.modules.setdefault("python_socketio", MagicMock())

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.schemas.gg_datasource import (
    DatasourceBulkConnectionResponse,
    DatasourceConnectionRequest,
    DatasourceConnectionResponse,
    DatasourceProcessingRequest,
    DatasourceProcessingResponse,
    DatasourceTypeCount,
    DatasourceTypeCountResponse,
    FileUploadBulkResponse,
    FileUploadResponse,
    GGDatasourceBulkCreate,
    GGDatasourceBulkResponse,
    GGDatasourceCreate,
    GGDatasourceStats,
    GGDatasourceUpdate,
    GGEmbeddingStatusResponse,
    MLWebhookRequest,
    MLWebhookResponse,
    ProcessingStatusUpdate,
    RegenerateEmbeddingResponse,
    ResolvedDatasourcesResponse,
)
from app.routes.gg_datasources import router as gg_router
from app.core.database import get_db

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_WS_ID   = "550e8400-e29b-41d4-a716-446655440000"
_CH_ID   = "550e8400-e29b-41d4-a716-446655440001"
_TH_ID   = "550e8400-e29b-41d4-a716-446655440002"
_MSG_ID  = "550e8400-e29b-41d4-a716-446655440003"
_DS_ID   = "550e8400-e29b-41d4-a716-446655440004"
_USER_ID = "550e8400-e29b-41d4-a716-446655440005"


# ---------------------------------------------------------------------------
# DB result helpers
# ---------------------------------------------------------------------------

def _scalar(value):
    r = MagicMock()
    r.scalar_one_or_none = MagicMock(return_value=value)
    r.scalar = MagicMock(return_value=0)
    r.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    return r


def _scalars_result(items):
    r = MagicMock()
    r.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=items)))
    r.scalar_one_or_none = MagicMock(return_value=None)
    r.all = MagicMock(return_value=items)
    return r


def _make_ds_mock(**overrides):
    ds = MagicMock()
    ds.id             = uuid.UUID(_DS_ID)
    ds.level          = "channel"
    ds.workspace_id   = None
    ds.channel_id     = uuid.UUID(_CH_ID)
    ds.thread_id      = None
    ds.message_id     = None
    ds.added_by       = uuid.UUID(_USER_ID)
    ds.name           = "test-datasource"
    ds.filename       = "test.pdf"
    ds.storage_type   = "local"
    ds.provider       = None
    ds.app_type       = None
    ds.config         = {}
    ds.datasource_metadata = {}
    ds.vault_unique_id     = None
    ds.file_size      = 1024
    ds.file_type      = "application/pdf"
    ds.file_url       = None
    ds.log_type       = None
    ds.is_active      = True
    ds.is_connected   = True
    ds.is_processed   = False
    ds.processing_status   = "pending"
    ds.error_message       = None
    ds.is_embedding_required = False
    ds.embedding_status    = 0
    ds.last_processed_at   = None
    ds.processing_time     = None
    ds.record_count        = 0
    ds.created_at          = None
    ds.updated_at          = None
    for k, v in overrides.items():
        setattr(ds, k, v)
    return ds


def _make_company_mock():
    c = MagicMock()
    c.id   = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    c.name = "Test Company"
    return c


def _make_client(mock_db, current_user=None):
    """Create a TestClient with mocked DB. Auth is patched by the autouse fixture."""
    app = FastAPI()
    app.include_router(gg_router, prefix="/gg-datasources")
    app.dependency_overrides[get_db] = lambda: mock_db
    return TestClient(app)


@pytest.fixture(autouse=True)
def patch_gg_datasources_auth(admin_user):
    """Keep get_current_user_required patched for the full duration of every test."""
    with patch(
        "app.routes.gg_datasources.get_current_user_required",
        new=AsyncMock(return_value=admin_user),
    ):
        yield


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def admin_user():
    user = MagicMock()
    user.id         = uuid.UUID(_USER_ID)
    user.company_id = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    user.email      = "admin@test.com"
    user.is_active  = True
    return user


@pytest.fixture
def mock_db():
    db = MagicMock()
    db.execute  = AsyncMock(return_value=_scalar(None))
    db.commit   = AsyncMock()
    db.rollback = AsyncMock()
    db.refresh  = AsyncMock()
    db.add      = MagicMock()
    db.delete   = MagicMock()
    return db


# ===========================================================================
# Schema Tests
# ===========================================================================


class TestFileUploadResponseSchema:
    @pytest.mark.unit
    def test_valid_creation(self):
        r = FileUploadResponse(
            filename="test.csv",
            file_size=2048,
            file_type="text/csv",
            file_url="https://storage/test.csv",
            storage_path="company/2025/test.csv",
            provider="local",
        )
        assert r.filename == "test.csv"
        assert r.file_size == 2048
        assert r.provider == "local"

    @pytest.mark.unit
    def test_missing_required_field_raises(self):
        with pytest.raises(ValidationError):
            FileUploadResponse(
                file_size=2048,
                file_type="text/csv",
                file_url="https://storage/test.csv",
                storage_path="company/2025/test.csv",
                provider="local",
            )


class TestFileUploadBulkResponseSchema:
    @pytest.mark.unit
    def test_valid(self):
        r = FileUploadBulkResponse(
            uploaded_files=[
                FileUploadResponse(
                    filename="a.csv",
                    file_size=100,
                    file_type="text/csv",
                    file_url="https://s/a.csv",
                    storage_path="p/a.csv",
                    provider="local",
                )
            ],
            failed_files=[],
            total_uploaded=1,
            total_failed=0,
        )
        assert r.total_uploaded == 1
        assert r.total_failed == 0

    @pytest.mark.unit
    def test_empty_lists(self):
        r = FileUploadBulkResponse(
            uploaded_files=[],
            failed_files=[],
            total_uploaded=0,
            total_failed=0,
        )
        assert r.uploaded_files == []
        assert r.failed_files == []


class TestGGDatasourceBulkCreateSchema:
    @pytest.mark.unit
    def test_valid_bulk(self):
        payload = GGDatasourceBulkCreate(
            datasources=[
                GGDatasourceCreate(
                    level="channel",
                    channel_id=_CH_ID,
                    name="DS1",
                    storage_type="local",
                )
            ]
        )
        assert len(payload.datasources) == 1

    @pytest.mark.unit
    def test_empty_list_rejected(self):
        with pytest.raises(ValidationError):
            GGDatasourceBulkCreate(datasources=[])


class TestGGDatasourceBulkResponseSchema:
    @pytest.mark.unit
    def test_valid(self):
        r = GGDatasourceBulkResponse(
            created_datasources=[],
            failed_datasources=[{"name": "x", "error": "db error"}],
            total_created=0,
            total_failed=1,
        )
        assert r.total_failed == 1


class TestGGDatasourceStatsSchema:
    @pytest.mark.unit
    def test_valid(self):
        stats = GGDatasourceStats(
            total_datasources=10,
            active_datasources=8,
            processed_datasources=5,
            pending_datasources=3,
            failed_datasources=2,
            total_file_size=1024000,
            storage_type_breakdown={"local": 6, "cloud": 4},
            provider_breakdown={"aws": 4},
        )
        assert stats.total_datasources == 10
        assert stats.storage_type_breakdown["local"] == 6


class TestDatasourceTypeCountSchema:
    @pytest.mark.unit
    def test_datasource_type_count(self):
        dtc = DatasourceTypeCount(type="local", count=5)
        assert dtc.type == "local"
        assert dtc.count == 5

    @pytest.mark.unit
    def test_datasource_type_count_response(self):
        resp = DatasourceTypeCountResponse(
            counts=[
                DatasourceTypeCount(type="local", count=3),
                DatasourceTypeCount(type="cloud", count=2),
            ],
            total_connected=5,
        )
        assert resp.total_connected == 5
        assert len(resp.counts) == 2


class TestDatasourceConnectionSchemas:
    @pytest.mark.unit
    def test_connection_response(self):
        r = DatasourceConnectionResponse(
            datasource_id=_DS_ID,
            is_connected=True,
            message="connected",
        )
        assert r.is_connected is True

    @pytest.mark.unit
    def test_connection_request_connect(self):
        req = DatasourceConnectionRequest(
            datasource_ids=[_DS_ID],
            action="connect",
        )
        assert req.action == "connect"

    @pytest.mark.unit
    def test_connection_request_disconnect(self):
        req = DatasourceConnectionRequest(
            datasource_ids=[_DS_ID],
            action="disconnect",
        )
        assert req.action == "disconnect"

    @pytest.mark.unit
    def test_connection_request_invalid_action(self):
        with pytest.raises(ValidationError):
            DatasourceConnectionRequest(
                datasource_ids=[_DS_ID],
                action="delete",
            )

    @pytest.mark.unit
    def test_connection_request_empty_ids(self):
        with pytest.raises(ValidationError):
            DatasourceConnectionRequest(
                datasource_ids=[],
                action="connect",
            )

    @pytest.mark.unit
    def test_bulk_connection_response(self):
        r = DatasourceBulkConnectionResponse(
            successful_operations=[],
            failed_operations=[],
            total_successful=0,
            total_failed=0,
            action_performed="connect",
            message="done",
        )
        assert r.action_performed == "connect"


class TestDatasourceProcessingSchemas:
    @pytest.mark.unit
    def test_processing_request(self):
        req = DatasourceProcessingRequest(datasource_id=_DS_ID)
        assert req.datasource_id == _DS_ID

    @pytest.mark.unit
    def test_processing_response(self):
        resp = DatasourceProcessingResponse(
            datasource_id=_DS_ID,
            status="processing_started",
            message="Background processing started",
        )
        assert resp.status == "processing_started"


class TestGGEmbeddingStatusResponseSchema:
    @pytest.mark.unit
    def test_valid(self):
        resp = GGEmbeddingStatusResponse(
            scope_level="channel",
            scope_id=_CH_ID,
            total_datasources=3,
            embedding_required=2,
            in_progress=1,
            completed=1,
            failed=0,
            not_required=1,
            datasources=[],
        )
        assert resp.scope_level == "channel"
        assert resp.total_datasources == 3

    @pytest.mark.unit
    def test_workspace_scope_level(self):
        resp = GGEmbeddingStatusResponse(
            scope_level="workspace",
            scope_id=_WS_ID,
            total_datasources=0,
            embedding_required=0,
            in_progress=0,
            completed=0,
            failed=0,
            not_required=0,
            datasources=[],
        )
        assert resp.scope_level == "workspace"

    @pytest.mark.unit
    def test_thread_scope_level(self):
        resp = GGEmbeddingStatusResponse(
            scope_level="thread",
            scope_id=_TH_ID,
            total_datasources=1,
            embedding_required=1,
            in_progress=0,
            completed=0,
            failed=0,
            not_required=0,
            datasources=[],
        )
        assert resp.scope_level == "thread"

    @pytest.mark.unit
    def test_message_scope_level(self):
        resp = GGEmbeddingStatusResponse(
            scope_level="message",
            scope_id=_MSG_ID,
            total_datasources=1,
            embedding_required=0,
            in_progress=0,
            completed=1,
            failed=0,
            not_required=0,
            datasources=[],
        )
        assert resp.scope_level == "message"


class TestMLWebhookSchemas:
    @pytest.mark.unit
    def test_webhook_request_success(self):
        req = MLWebhookRequest(
            vaultUniqueIds=[str(uuid.uuid4())],
            status="success",
        )
        assert req.status == "success"

    @pytest.mark.unit
    def test_webhook_request_failed(self):
        req = MLWebhookRequest(
            vaultUniqueIds=[str(uuid.uuid4())],
            status="failed",
            message="embedding failed",
        )
        assert req.status == "failed"
        assert req.message == "embedding failed"

    @pytest.mark.unit
    def test_webhook_request_with_processing_time(self):
        req = MLWebhookRequest(
            vaultUniqueIds=[str(uuid.uuid4())],
            status="success",
            processingTime=500,
        )
        assert req.processingTime == 500

    @pytest.mark.unit
    def test_webhook_response(self):
        resp = MLWebhookResponse(
            message="Updated 1 datasource(s)",
            processed_count=1,
            failed_count=0,
        )
        assert resp.processed_count == 1


class TestRegenerateEmbeddingResponseSchema:
    @pytest.mark.unit
    def test_success_response(self):
        resp = RegenerateEmbeddingResponse(
            success=True,
            message="Triggered",
            datasource_id=_DS_ID,
            embedding_status=1,
            status_description="in_progress",
        )
        assert resp.success is True
        assert resp.embedding_status == 1

    @pytest.mark.unit
    def test_failure_response(self):
        resp = RegenerateEmbeddingResponse(
            success=False,
            message="Failed to trigger embedding",
            datasource_id=_DS_ID,
            embedding_status=3,
            status_description="failed",
        )
        assert resp.success is False
        assert resp.embedding_status == 3


# ===========================================================================
# Route Tests
# ===========================================================================


class TestSupportedLogTypes:
    @pytest.mark.unit
    def test_returns_list(self, mock_db, admin_user):
        with patch("app.routes.gg_datasources.settings") as mock_settings:
            mock_settings.SUPPORTED_LOG_TYPES = ["nginx", "apache", "syslog"]
            client = _make_client(mock_db, admin_user)
            resp = client.get("/gg-datasources/supported-log-types")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.unit
    def test_returns_configured_types(self, mock_db, admin_user):
        with patch("app.routes.gg_datasources.settings") as mock_settings:
            mock_settings.SUPPORTED_LOG_TYPES = ["nginx", "apache"]
            client = _make_client(mock_db, admin_user)
            resp = client.get("/gg-datasources/supported-log-types")
        assert resp.status_code == 200
        data = resp.json()
        assert "nginx" in data
        assert "apache" in data


class TestEnvironment:
    @pytest.mark.unit
    def test_returns_dict(self, mock_db, admin_user):
        with patch(
            "app.services.vault_data_builder.get_environment_info",
            return_value={"env": "test", "vault": "disabled"},
        ):
            client = _make_client(mock_db, admin_user)
            resp = client.get("/gg-datasources/environment")
        assert resp.status_code == 200
        assert isinstance(resp.json(), dict)


class TestUploadFile:
    @pytest.mark.unit
    def test_upload_success(self, mock_db, admin_user):
        company = _make_company_mock()
        mock_db.execute = AsyncMock(return_value=_scalar(company))
        upload_result = {
            "storage_path": "company/2025/test.csv",
            "file_url": "https://storage/test.csv",
            "provider": "local",
            "bucket_name": None,
            "region": None,
            "file_content": b"data",
            "file_size": 4,
            "file_type": "text/csv",
            "original_filename": "test.csv",
        }
        with patch(
            "app.routes.gg_datasources._upload_single_file",
            new=AsyncMock(return_value=upload_result),
        ):
            client = _make_client(mock_db, admin_user)
            resp = client.post(
                "/gg-datasources/upload",
                files={"file": ("test.csv", b"col1,col2\n1,2", "text/csv")},
                data={"isValidationRequired": "false"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["filename"] == "test.csv"

    @pytest.mark.unit
    def test_upload_company_not_found_returns_404(self, mock_db, admin_user):
        mock_db.execute = AsyncMock(return_value=_scalar(None))
        client = _make_client(mock_db, admin_user)
        resp = client.post(
            "/gg-datasources/upload",
            files={"file": ("test.csv", b"data", "text/csv")},
            data={"isValidationRequired": "false"},
        )
        assert resp.status_code == 404

    @pytest.mark.unit
    def test_upload_validation_failure_returns_400(self, mock_db, admin_user):
        company = _make_company_mock()
        mock_db.execute = AsyncMock(return_value=_scalar(company))
        from fastapi import HTTPException as FastAPIHTTPException
        with patch(
            "app.routes.gg_datasources._upload_single_file",
            new=AsyncMock(side_effect=FastAPIHTTPException(status_code=400, detail="File validation failed")),
        ):
            client = _make_client(mock_db, admin_user)
            resp = client.post(
                "/gg-datasources/upload",
                files={"file": ("test.csv", b"bad data", "text/csv")},
                data={"isValidationRequired": "true"},
            )
        assert resp.status_code == 400

    @pytest.mark.unit
    def test_upload_storage_error_returns_500(self, mock_db, admin_user):
        company = _make_company_mock()
        mock_db.execute = AsyncMock(return_value=_scalar(company))
        with patch(
            "app.routes.gg_datasources._upload_single_file",
            new=AsyncMock(side_effect=Exception("Storage connection refused")),
        ):
            client = _make_client(mock_db, admin_user)
            resp = client.post(
                "/gg-datasources/upload",
                files={"file": ("test.csv", b"data", "text/csv")},
                data={"isValidationRequired": "false"},
            )
        assert resp.status_code == 500


class TestUploadFilesBulk:
    @pytest.mark.unit
    def test_bulk_upload_all_success(self, mock_db, admin_user):
        company = _make_company_mock()
        mock_db.execute = AsyncMock(return_value=_scalar(company))

        def _upload_side_effect(file, company, is_validation_required):
            return {
                "storage_path": f"company/2025/{file.filename}",
                "file_url": f"https://storage/{file.filename}",
                "provider": "local",
                "bucket_name": None,
                "region": None,
                "file_content": b"data",
                "file_size": 4,
                "file_type": "text/csv",
                "original_filename": file.filename,
            }

        with patch(
            "app.routes.gg_datasources._upload_single_file",
            new=AsyncMock(side_effect=_upload_side_effect),
        ):
            client = _make_client(mock_db, admin_user)
            resp = client.post(
                "/gg-datasources/upload/bulk",
                files=[
                    ("files", ("a.csv", b"data1", "text/csv")),
                    ("files", ("b.csv", b"data2", "text/csv")),
                ],
                data={"isValidationRequired": "false"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_uploaded"] == 2
        assert data["total_failed"] == 0

    @pytest.mark.unit
    def test_bulk_upload_partial_failure(self, mock_db, admin_user):
        company = _make_company_mock()
        mock_db.execute = AsyncMock(return_value=_scalar(company))
        from fastapi import HTTPException as FastAPIHTTPException
        call_count = [0]

        async def _side_effect(file, company, is_validation_required):
            call_count[0] += 1
            if call_count[0] == 2:
                raise FastAPIHTTPException(status_code=400, detail="Validation failed")
            return {
                "storage_path": f"company/2025/{file.filename}",
                "file_url": f"https://storage/{file.filename}",
                "provider": "local",
                "bucket_name": None,
                "region": None,
                "file_content": b"data",
                "file_size": 4,
                "file_type": "text/csv",
                "original_filename": file.filename,
            }

        with patch(
            "app.routes.gg_datasources._upload_single_file",
            new=AsyncMock(side_effect=_side_effect),
        ):
            client = _make_client(mock_db, admin_user)
            resp = client.post(
                "/gg-datasources/upload/bulk",
                files=[
                    ("files", ("a.csv", b"data1", "text/csv")),
                    ("files", ("b.csv", b"data2", "text/csv")),
                ],
                data={"isValidationRequired": "false"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_uploaded"] == 1
        assert data["total_failed"] == 1

    @pytest.mark.unit
    def test_bulk_upload_company_not_found(self, mock_db, admin_user):
        mock_db.execute = AsyncMock(return_value=_scalar(None))
        client = _make_client(mock_db, admin_user)
        resp = client.post(
            "/gg-datasources/upload/bulk",
            files=[("files", ("a.csv", b"data", "text/csv"))],
            data={"isValidationRequired": "false"},
        )
        assert resp.status_code == 404


class TestCreateFromUpload:
    _upload_result = {
        "storage_path": "company/2025/test.csv",
        "file_url": "https://storage/test.csv",
        "provider": "local",
        "bucket_name": None,
        "region": None,
        "file_content": b"data",
        "file_size": 4,
        "file_type": "text/csv",
        "original_filename": "test.csv",
    }

    def _make_ds_for_level(self, level, scope_id):
        ds = _make_ds_mock(
            level=level,
            name="Test",
            filename="test.csv",
            storage_type="local",
        )
        if level == "workspace":
            ds.workspace_id = uuid.UUID(scope_id)
            ds.channel_id = None
            ds.thread_id = None
            ds.message_id = None
        elif level == "channel":
            ds.channel_id = uuid.UUID(scope_id)
            ds.workspace_id = None
            ds.thread_id = None
            ds.message_id = None
        elif level == "thread":
            ds.thread_id = uuid.UUID(scope_id)
            ds.channel_id = None
            ds.workspace_id = None
            ds.message_id = None
        elif level == "message":
            ds.message_id = uuid.UUID(scope_id)
            ds.channel_id = None
            ds.workspace_id = None
            ds.thread_id = None
        return ds

    @pytest.mark.unit
    def test_from_upload_channel_scope_success(self, mock_db, admin_user):
        company = _make_company_mock()
        ds = self._make_ds_for_level("channel", _CH_ID)

        mock_db.execute = AsyncMock(return_value=_scalar(company))

        async def _refresh(obj):
            obj.id = ds.id
            obj.level = ds.level
            obj.channel_id = ds.channel_id
            obj.workspace_id = ds.workspace_id
            obj.thread_id = ds.thread_id
            obj.message_id = ds.message_id
            obj.added_by = ds.added_by
            obj.name = ds.name
            obj.filename = ds.filename
            obj.storage_type = ds.storage_type
            obj.provider = ds.provider
            obj.app_type = ds.app_type
            obj.config = ds.config
            obj.datasource_metadata = ds.datasource_metadata
            obj.vault_unique_id = ds.vault_unique_id
            obj.file_size = ds.file_size
            obj.file_type = ds.file_type
            obj.file_url = ds.file_url
            obj.log_type = ds.log_type
            obj.is_active = ds.is_active
            obj.is_connected = ds.is_connected
            obj.is_processed = ds.is_processed
            obj.processing_status = ds.processing_status
            obj.error_message = ds.error_message
            obj.is_embedding_required = ds.is_embedding_required
            obj.embedding_status = ds.embedding_status
            obj.last_processed_at = ds.last_processed_at
            obj.processing_time = ds.processing_time
            obj.record_count = ds.record_count
            obj.created_at = ds.created_at
            obj.updated_at = ds.updated_at

        mock_db.refresh = AsyncMock(side_effect=_refresh)

        with patch("app.routes.gg_datasources._upload_single_file", new=AsyncMock(return_value=self._upload_result)), \
             patch("app.routes.gg_datasources.generate_datasource_metadata", return_value={}), \
             patch("app.routes.gg_datasources.clean_metadata", return_value={}), \
             patch("app.routes.gg_datasources.enhance_datasource_metadata", new=AsyncMock(return_value={})), \
             patch("app.routes.gg_datasources.handle_vault_integration", new=AsyncMock(return_value=None)):
            client = _make_client(mock_db, admin_user)
            resp = client.post(
                "/gg-datasources/from-upload",
                files={"file": ("test.csv", b"data", "text/csv")},
                data={"level": "channel", "scope_id": _CH_ID, "isValidationRequired": "false"},
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data["level"] == "channel"

    @pytest.mark.unit
    def test_from_upload_workspace_scope_success(self, mock_db, admin_user):
        company = _make_company_mock()
        ds = self._make_ds_for_level("workspace", _WS_ID)

        mock_db.execute = AsyncMock(return_value=_scalar(company))

        async def _refresh(obj):
            for attr in ["id", "level", "workspace_id", "channel_id", "thread_id", "message_id",
                         "added_by", "name", "filename", "storage_type", "provider", "app_type",
                         "config", "datasource_metadata", "vault_unique_id", "file_size", "file_type",
                         "file_url", "log_type", "is_active", "is_connected", "is_processed",
                         "processing_status", "error_message", "is_embedding_required", "embedding_status",
                         "last_processed_at", "processing_time", "record_count", "created_at", "updated_at"]:
                setattr(obj, attr, getattr(ds, attr))

        mock_db.refresh = AsyncMock(side_effect=_refresh)

        with patch("app.routes.gg_datasources._upload_single_file", new=AsyncMock(return_value=self._upload_result)), \
             patch("app.routes.gg_datasources.generate_datasource_metadata", return_value={}), \
             patch("app.routes.gg_datasources.clean_metadata", return_value={}), \
             patch("app.routes.gg_datasources.enhance_datasource_metadata", new=AsyncMock(return_value={})), \
             patch("app.routes.gg_datasources.handle_vault_integration", new=AsyncMock(return_value=None)):
            client = _make_client(mock_db, admin_user)
            resp = client.post(
                "/gg-datasources/from-upload",
                files={"file": ("test.csv", b"data", "text/csv")},
                data={"level": "workspace", "scope_id": _WS_ID, "isValidationRequired": "false"},
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data["level"] == "workspace"

    @pytest.mark.unit
    def test_from_upload_thread_scope_success(self, mock_db, admin_user):
        company = _make_company_mock()
        ds = self._make_ds_for_level("thread", _TH_ID)

        mock_db.execute = AsyncMock(return_value=_scalar(company))

        async def _refresh(obj):
            for attr in ["id", "level", "workspace_id", "channel_id", "thread_id", "message_id",
                         "added_by", "name", "filename", "storage_type", "provider", "app_type",
                         "config", "datasource_metadata", "vault_unique_id", "file_size", "file_type",
                         "file_url", "log_type", "is_active", "is_connected", "is_processed",
                         "processing_status", "error_message", "is_embedding_required", "embedding_status",
                         "last_processed_at", "processing_time", "record_count", "created_at", "updated_at"]:
                setattr(obj, attr, getattr(ds, attr))

        mock_db.refresh = AsyncMock(side_effect=_refresh)

        with patch("app.routes.gg_datasources._upload_single_file", new=AsyncMock(return_value=self._upload_result)), \
             patch("app.routes.gg_datasources.generate_datasource_metadata", return_value={}), \
             patch("app.routes.gg_datasources.clean_metadata", return_value={}), \
             patch("app.routes.gg_datasources.enhance_datasource_metadata", new=AsyncMock(return_value={})), \
             patch("app.routes.gg_datasources.handle_vault_integration", new=AsyncMock(return_value=None)):
            client = _make_client(mock_db, admin_user)
            resp = client.post(
                "/gg-datasources/from-upload",
                files={"file": ("test.csv", b"data", "text/csv")},
                data={"level": "thread", "scope_id": _TH_ID, "isValidationRequired": "false"},
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data["level"] == "thread"

    @pytest.mark.unit
    def test_from_upload_message_scope_success(self, mock_db, admin_user):
        company = _make_company_mock()
        ds = self._make_ds_for_level("message", _MSG_ID)

        mock_db.execute = AsyncMock(return_value=_scalar(company))

        async def _refresh(obj):
            for attr in ["id", "level", "workspace_id", "channel_id", "thread_id", "message_id",
                         "added_by", "name", "filename", "storage_type", "provider", "app_type",
                         "config", "datasource_metadata", "vault_unique_id", "file_size", "file_type",
                         "file_url", "log_type", "is_active", "is_connected", "is_processed",
                         "processing_status", "error_message", "is_embedding_required", "embedding_status",
                         "last_processed_at", "processing_time", "record_count", "created_at", "updated_at"]:
                setattr(obj, attr, getattr(ds, attr))

        mock_db.refresh = AsyncMock(side_effect=_refresh)

        with patch("app.routes.gg_datasources._upload_single_file", new=AsyncMock(return_value=self._upload_result)), \
             patch("app.routes.gg_datasources.generate_datasource_metadata", return_value={}), \
             patch("app.routes.gg_datasources.clean_metadata", return_value={}), \
             patch("app.routes.gg_datasources.enhance_datasource_metadata", new=AsyncMock(return_value={})), \
             patch("app.routes.gg_datasources.handle_vault_integration", new=AsyncMock(return_value=None)):
            client = _make_client(mock_db, admin_user)
            resp = client.post(
                "/gg-datasources/from-upload",
                files={"file": ("test.csv", b"data", "text/csv")},
                data={"level": "message", "scope_id": _MSG_ID, "isValidationRequired": "false"},
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data["level"] == "message"

    @pytest.mark.unit
    def test_from_upload_invalid_level_returns_400(self, mock_db, admin_user):
        client = _make_client(mock_db, admin_user)
        resp = client.post(
            "/gg-datasources/from-upload",
            files={"file": ("test.csv", b"data", "text/csv")},
            data={"level": "organization", "scope_id": _CH_ID, "isValidationRequired": "false"},
        )
        assert resp.status_code == 400

    @pytest.mark.unit
    def test_from_upload_company_not_found_returns_404(self, mock_db, admin_user):
        mock_db.execute = AsyncMock(return_value=_scalar(None))
        client = _make_client(mock_db, admin_user)
        resp = client.post(
            "/gg-datasources/from-upload",
            files={"file": ("test.csv", b"data", "text/csv")},
            data={"level": "channel", "scope_id": _CH_ID, "isValidationRequired": "false"},
        )
        assert resp.status_code == 404

    @pytest.mark.unit
    def test_from_upload_auto_generates_name(self, mock_db, admin_user):
        company = _make_company_mock()
        ds = self._make_ds_for_level("channel", _CH_ID)
        ds.name = "My File"

        mock_db.execute = AsyncMock(return_value=_scalar(company))

        async def _refresh(obj):
            for attr in ["id", "level", "workspace_id", "channel_id", "thread_id", "message_id",
                         "added_by", "name", "filename", "storage_type", "provider", "app_type",
                         "config", "datasource_metadata", "vault_unique_id", "file_size", "file_type",
                         "file_url", "log_type", "is_active", "is_connected", "is_processed",
                         "processing_status", "error_message", "is_embedding_required", "embedding_status",
                         "last_processed_at", "processing_time", "record_count", "created_at", "updated_at"]:
                setattr(obj, attr, getattr(ds, attr))

        mock_db.refresh = AsyncMock(side_effect=_refresh)

        upload_result = dict(self._upload_result, original_filename="my_file.csv")
        with patch("app.routes.gg_datasources._upload_single_file", new=AsyncMock(return_value=upload_result)), \
             patch("app.routes.gg_datasources.generate_datasource_metadata", return_value={}), \
             patch("app.routes.gg_datasources.clean_metadata", return_value={}), \
             patch("app.routes.gg_datasources.enhance_datasource_metadata", new=AsyncMock(return_value={})), \
             patch("app.routes.gg_datasources.handle_vault_integration", new=AsyncMock(return_value=None)):
            client = _make_client(mock_db, admin_user)
            # No name field provided — should auto-generate
            resp = client.post(
                "/gg-datasources/from-upload",
                files={"file": ("my_file.csv", b"data", "text/csv")},
                data={"level": "channel", "scope_id": _CH_ID, "isValidationRequired": "false"},
            )
        assert resp.status_code == 201

    @pytest.mark.unit
    def test_from_upload_custom_name_used(self, mock_db, admin_user):
        company = _make_company_mock()
        ds = self._make_ds_for_level("channel", _CH_ID)
        ds.name = "Custom Name"

        mock_db.execute = AsyncMock(return_value=_scalar(company))

        async def _refresh(obj):
            for attr in ["id", "level", "workspace_id", "channel_id", "thread_id", "message_id",
                         "added_by", "name", "filename", "storage_type", "provider", "app_type",
                         "config", "datasource_metadata", "vault_unique_id", "file_size", "file_type",
                         "file_url", "log_type", "is_active", "is_connected", "is_processed",
                         "processing_status", "error_message", "is_embedding_required", "embedding_status",
                         "last_processed_at", "processing_time", "record_count", "created_at", "updated_at"]:
                setattr(obj, attr, getattr(ds, attr))

        mock_db.refresh = AsyncMock(side_effect=_refresh)

        with patch("app.routes.gg_datasources._upload_single_file", new=AsyncMock(return_value=self._upload_result)), \
             patch("app.routes.gg_datasources.generate_datasource_metadata", return_value={}), \
             patch("app.routes.gg_datasources.clean_metadata", return_value={}), \
             patch("app.routes.gg_datasources.enhance_datasource_metadata", new=AsyncMock(return_value={})), \
             patch("app.routes.gg_datasources.handle_vault_integration", new=AsyncMock(return_value=None)):
            client = _make_client(mock_db, admin_user)
            resp = client.post(
                "/gg-datasources/from-upload",
                files={"file": ("test.csv", b"data", "text/csv")},
                data={"level": "channel", "scope_id": _CH_ID, "name": "Custom Name", "isValidationRequired": "false"},
            )
        assert resp.status_code == 201
        assert resp.json()["name"] == "Custom Name"


class TestCreateFromUploadBulk:
    _upload_result = {
        "storage_path": "company/2025/test.csv",
        "file_url": "https://storage/test.csv",
        "provider": "local",
        "bucket_name": None,
        "region": None,
        "file_content": b"data",
        "file_size": 4,
        "file_type": "text/csv",
        "original_filename": "test.csv",
    }

    @pytest.mark.unit
    def test_bulk_from_upload_success(self, mock_db, admin_user):
        company = _make_company_mock()
        ds = _make_ds_mock(level="channel", name="Test DS")

        mock_db.execute = AsyncMock(return_value=_scalar(company))

        async def _refresh(obj):
            for attr in ["id", "level", "workspace_id", "channel_id", "thread_id", "message_id",
                         "added_by", "name", "filename", "storage_type", "provider", "app_type",
                         "config", "datasource_metadata", "vault_unique_id", "file_size", "file_type",
                         "file_url", "log_type", "is_active", "is_connected", "is_processed",
                         "processing_status", "error_message", "is_embedding_required", "embedding_status",
                         "last_processed_at", "processing_time", "record_count", "created_at", "updated_at"]:
                setattr(obj, attr, getattr(ds, attr))

        mock_db.refresh = AsyncMock(side_effect=_refresh)

        ds_list = [{"level": "channel", "scope_id": _CH_ID, "name": "Test DS"}]
        with patch("app.routes.gg_datasources._upload_single_file", new=AsyncMock(return_value=self._upload_result)), \
             patch("app.routes.gg_datasources.generate_datasource_metadata", return_value={}), \
             patch("app.routes.gg_datasources.clean_metadata", return_value={}), \
             patch("app.routes.gg_datasources.enhance_datasource_metadata", new=AsyncMock(return_value={})), \
             patch("app.routes.gg_datasources.handle_vault_integration", new=AsyncMock(return_value=None)):
            client = _make_client(mock_db, admin_user)
            resp = client.post(
                "/gg-datasources/from-upload/bulk",
                files=[("files", ("test.csv", b"data", "text/csv"))],
                data={"datasources_json": json.dumps(ds_list), "isValidationRequired": "false"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_created"] == 1

    @pytest.mark.unit
    def test_bulk_from_upload_file_count_mismatch_returns_400(self, mock_db, admin_user):
        company = _make_company_mock()
        mock_db.execute = AsyncMock(return_value=_scalar(company))
        ds_list = [
            {"level": "channel", "scope_id": _CH_ID, "name": "DS1"},
            {"level": "channel", "scope_id": _CH_ID, "name": "DS2"},
        ]
        client = _make_client(mock_db, admin_user)
        resp = client.post(
            "/gg-datasources/from-upload/bulk",
            files=[("files", ("test.csv", b"data", "text/csv"))],
            data={"datasources_json": json.dumps(ds_list), "isValidationRequired": "false"},
        )
        assert resp.status_code == 400

    @pytest.mark.unit
    def test_bulk_from_upload_invalid_json_returns_400(self, mock_db, admin_user):
        client = _make_client(mock_db, admin_user)
        resp = client.post(
            "/gg-datasources/from-upload/bulk",
            files=[("files", ("test.csv", b"data", "text/csv"))],
            data={"datasources_json": "not-valid-json", "isValidationRequired": "false"},
        )
        assert resp.status_code == 400

    @pytest.mark.unit
    def test_bulk_from_upload_invalid_level_goes_to_failed(self, mock_db, admin_user):
        company = _make_company_mock()
        mock_db.execute = AsyncMock(return_value=_scalar(company))
        ds_list = [{"level": "bad_level", "scope_id": _CH_ID, "name": "DS1"}]
        with patch("app.routes.gg_datasources._upload_single_file", new=AsyncMock(return_value=self._upload_result)), \
             patch("app.routes.gg_datasources.generate_datasource_metadata", return_value={}), \
             patch("app.routes.gg_datasources.clean_metadata", return_value={}), \
             patch("app.routes.gg_datasources.enhance_datasource_metadata", new=AsyncMock(return_value={})), \
             patch("app.routes.gg_datasources.handle_vault_integration", new=AsyncMock(return_value=None)):
            client = _make_client(mock_db, admin_user)
            resp = client.post(
                "/gg-datasources/from-upload/bulk",
                files=[("files", ("test.csv", b"data", "text/csv"))],
                data={"datasources_json": json.dumps(ds_list), "isValidationRequired": "false"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_failed"] == 1
        assert data["total_created"] == 0


class TestBulkCreate:
    def _channel_ds_payload(self):
        return {
            "level": "channel",
            "channel_id": _CH_ID,
            "name": "Channel DS",
            "storage_type": "local",
        }

    @pytest.mark.unit
    def test_bulk_create_success(self, mock_db, admin_user):
        ds = _make_ds_mock()

        async def _refresh(obj):
            for attr in ["id", "level", "workspace_id", "channel_id", "thread_id", "message_id",
                         "added_by", "name", "filename", "storage_type", "provider", "app_type",
                         "config", "datasource_metadata", "vault_unique_id", "file_size", "file_type",
                         "file_url", "log_type", "is_active", "is_connected", "is_processed",
                         "processing_status", "error_message", "is_embedding_required", "embedding_status",
                         "last_processed_at", "processing_time", "record_count", "created_at", "updated_at"]:
                setattr(obj, attr, getattr(ds, attr))

        mock_db.refresh = AsyncMock(side_effect=_refresh)
        client = _make_client(mock_db, admin_user)
        resp = client.post(
            "/gg-datasources/bulk",
            json={"datasources": [self._channel_ds_payload()]},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["total_created"] == 1

    @pytest.mark.unit
    def test_bulk_create_db_error_goes_to_failed(self, mock_db, admin_user):
        mock_db.commit = AsyncMock(side_effect=Exception("DB error"))
        client = _make_client(mock_db, admin_user)
        resp = client.post(
            "/gg-datasources/bulk",
            json={"datasources": [self._channel_ds_payload()]},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["total_failed"] == 1
        assert data["total_created"] == 0

    @pytest.mark.unit
    def test_bulk_create_empty_list_returns_422(self, mock_db, admin_user):
        client = _make_client(mock_db, admin_user)
        resp = client.post(
            "/gg-datasources/bulk",
            json={"datasources": []},
        )
        assert resp.status_code == 422

    @pytest.mark.unit
    def test_bulk_create_mixed_scopes(self, mock_db, admin_user):
        ds = _make_ds_mock()

        async def _refresh(obj):
            for attr in ["id", "level", "workspace_id", "channel_id", "thread_id", "message_id",
                         "added_by", "name", "filename", "storage_type", "provider", "app_type",
                         "config", "datasource_metadata", "vault_unique_id", "file_size", "file_type",
                         "file_url", "log_type", "is_active", "is_connected", "is_processed",
                         "processing_status", "error_message", "is_embedding_required", "embedding_status",
                         "last_processed_at", "processing_time", "record_count", "created_at", "updated_at"]:
                setattr(obj, attr, getattr(ds, attr))

        mock_db.refresh = AsyncMock(side_effect=_refresh)
        client = _make_client(mock_db, admin_user)
        resp = client.post(
            "/gg-datasources/bulk",
            json={
                "datasources": [
                    {"level": "workspace", "workspace_id": _WS_ID, "name": "WS DS", "storage_type": "local"},
                    {"level": "channel", "channel_id": _CH_ID, "name": "CH DS", "storage_type": "local"},
                    {"level": "thread", "thread_id": _TH_ID, "name": "TH DS", "storage_type": "local"},
                    {"level": "message", "message_id": _MSG_ID, "name": "MSG DS", "storage_type": "local"},
                ]
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["total_created"] + data["total_failed"] == 4


class TestCreateDatasource:
    def _make_refresh(self, ds):
        async def _refresh(obj):
            for attr in ["id", "level", "workspace_id", "channel_id", "thread_id", "message_id",
                         "added_by", "name", "filename", "storage_type", "provider", "app_type",
                         "config", "datasource_metadata", "vault_unique_id", "file_size", "file_type",
                         "file_url", "log_type", "is_active", "is_connected", "is_processed",
                         "processing_status", "error_message", "is_embedding_required", "embedding_status",
                         "last_processed_at", "processing_time", "record_count", "created_at", "updated_at"]:
                setattr(obj, attr, getattr(ds, attr))
        return _refresh

    @pytest.mark.unit
    def test_create_channel_datasource(self, mock_db, admin_user):
        ds = _make_ds_mock(level="channel")
        mock_db.refresh = AsyncMock(side_effect=self._make_refresh(ds))
        client = _make_client(mock_db, admin_user)
        resp = client.post(
            "/gg-datasources/",
            json={"level": "channel", "channel_id": _CH_ID, "name": "CH DS", "storage_type": "local"},
        )
        assert resp.status_code == 201
        assert resp.json()["level"] == "channel"

    @pytest.mark.unit
    def test_create_workspace_datasource(self, mock_db, admin_user):
        ds = _make_ds_mock(level="workspace", workspace_id=uuid.UUID(_WS_ID), channel_id=None)
        mock_db.refresh = AsyncMock(side_effect=self._make_refresh(ds))
        client = _make_client(mock_db, admin_user)
        resp = client.post(
            "/gg-datasources/",
            json={"level": "workspace", "workspace_id": _WS_ID, "name": "WS DS", "storage_type": "local"},
        )
        assert resp.status_code == 201
        assert resp.json()["level"] == "workspace"

    @pytest.mark.unit
    def test_create_thread_datasource(self, mock_db, admin_user):
        ds = _make_ds_mock(level="thread", thread_id=uuid.UUID(_TH_ID), channel_id=None)
        mock_db.refresh = AsyncMock(side_effect=self._make_refresh(ds))
        client = _make_client(mock_db, admin_user)
        resp = client.post(
            "/gg-datasources/",
            json={"level": "thread", "thread_id": _TH_ID, "name": "TH DS", "storage_type": "local"},
        )
        assert resp.status_code == 201
        assert resp.json()["level"] == "thread"

    @pytest.mark.unit
    def test_create_message_datasource(self, mock_db, admin_user):
        ds = _make_ds_mock(level="message", message_id=uuid.UUID(_MSG_ID), channel_id=None)
        mock_db.refresh = AsyncMock(side_effect=self._make_refresh(ds))
        client = _make_client(mock_db, admin_user)
        resp = client.post(
            "/gg-datasources/",
            json={"level": "message", "message_id": _MSG_ID, "name": "MSG DS", "storage_type": "local"},
        )
        assert resp.status_code == 201
        assert resp.json()["level"] == "message"

    @pytest.mark.unit
    def test_create_mismatched_level_returns_422(self, mock_db, admin_user):
        client = _make_client(mock_db, admin_user)
        resp = client.post(
            "/gg-datasources/",
            json={"level": "channel", "workspace_id": _WS_ID, "name": "DS", "storage_type": "local"},
        )
        assert resp.status_code == 422

    @pytest.mark.unit
    def test_create_db_error_returns_400(self, mock_db, admin_user):
        mock_db.commit = AsyncMock(side_effect=Exception("Unique constraint violation"))
        client = _make_client(mock_db, admin_user)
        resp = client.post(
            "/gg-datasources/",
            json={"level": "channel", "channel_id": _CH_ID, "name": "DS", "storage_type": "local"},
        )
        assert resp.status_code == 400


class TestGetResolvedDatasources:
    @pytest.mark.unit
    def test_resolved_with_channel_id(self, mock_db, admin_user):
        ds = _make_ds_mock(level="channel")
        mock_db.execute = AsyncMock(return_value=_scalars_result([ds]))
        client = _make_client(mock_db, admin_user)
        resp = client.get(f"/gg-datasources/resolved?channel_id={_CH_ID}")
        assert resp.status_code == 200
        data = resp.json()
        assert "channel" in data

    @pytest.mark.unit
    def test_resolved_with_all_scopes(self, mock_db, admin_user):
        ws_ds = _make_ds_mock(level="workspace", workspace_id=uuid.UUID(_WS_ID), channel_id=None)
        ch_ds = _make_ds_mock(level="channel")
        mock_db.execute = AsyncMock(
            side_effect=[
                _scalars_result([ws_ds]),
                _scalars_result([ch_ds]),
                _scalars_result([]),
                _scalars_result([]),
            ]
        )
        client = _make_client(mock_db, admin_user)
        resp = client.get(f"/gg-datasources/resolved?workspace_id={_WS_ID}&channel_id={_CH_ID}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2

    @pytest.mark.unit
    def test_resolved_no_scope_returns_empty(self, mock_db, admin_user):
        client = _make_client(mock_db, admin_user)
        resp = client.get("/gg-datasources/resolved")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0


class TestGetStats:
    @pytest.mark.unit
    def test_stats_no_scope(self, mock_db, admin_user):
        ds = _make_ds_mock(is_active=True, is_processed=False, processing_status="pending",
                           storage_type="local", file_size=1024)
        mock_db.execute = AsyncMock(return_value=_scalars_result([ds]))
        client = _make_client(mock_db, admin_user)
        resp = client.get("/gg-datasources/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_datasources" in data
        assert data["total_datasources"] == 1

    @pytest.mark.unit
    def test_stats_with_channel_filter(self, mock_db, admin_user):
        ds = _make_ds_mock()
        mock_db.execute = AsyncMock(return_value=_scalars_result([ds]))
        client = _make_client(mock_db, admin_user)
        resp = client.get(f"/gg-datasources/stats?channel_id={_CH_ID}")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_datasources" in data

    @pytest.mark.unit
    def test_stats_aggregates_correctly(self, mock_db, admin_user):
        ds1 = _make_ds_mock(is_active=True, is_processed=True, processing_status="completed",
                            storage_type="local", file_size=500)
        ds2 = _make_ds_mock(is_active=True, is_processed=False, processing_status="failed",
                            storage_type="cloud", file_size=200, provider="aws")
        mock_db.execute = AsyncMock(return_value=_scalars_result([ds1, ds2]))
        client = _make_client(mock_db, admin_user)
        resp = client.get("/gg-datasources/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_datasources"] == 2
        assert data["total_file_size"] == 700

    @pytest.mark.unit
    def test_stats_with_level_filter(self, mock_db, admin_user):
        ds = _make_ds_mock(level="workspace", workspace_id=uuid.UUID(_WS_ID), channel_id=None)
        mock_db.execute = AsyncMock(return_value=_scalars_result([ds]))
        client = _make_client(mock_db, admin_user)
        resp = client.get("/gg-datasources/stats?level=workspace")
        assert resp.status_code == 200


class TestGetCount:
    @pytest.mark.unit
    def test_count_no_scope(self, mock_db, admin_user):
        row = MagicMock()
        row.storage_type = "local"
        row.cnt = 2
        result = MagicMock()
        result.all = MagicMock(return_value=[row])
        mock_db.execute = AsyncMock(return_value=result)
        client = _make_client(mock_db, admin_user)
        resp = client.get("/gg-datasources/count")
        assert resp.status_code == 200
        data = resp.json()
        assert "counts" in data
        assert "total_connected" in data

    @pytest.mark.unit
    def test_count_types_are_correct(self, mock_db, admin_user):
        row = MagicMock()
        row.storage_type = "cloud"
        row.cnt = 3
        result = MagicMock()
        result.all = MagicMock(return_value=[row])
        mock_db.execute = AsyncMock(return_value=result)
        client = _make_client(mock_db, admin_user)
        resp = client.get("/gg-datasources/count")
        assert resp.status_code == 200
        data = resp.json()
        cloud_count = next((c["count"] for c in data["counts"] if c["type"] == "cloud"), 0)
        assert cloud_count == 3

    @pytest.mark.unit
    def test_count_with_channel_filter(self, mock_db, admin_user):
        result = MagicMock()
        result.all = MagicMock(return_value=[])
        mock_db.execute = AsyncMock(return_value=result)
        client = _make_client(mock_db, admin_user)
        resp = client.get(f"/gg-datasources/count?channel_id={_CH_ID}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_connected"] == 0


class TestListDatasources:
    @pytest.mark.unit
    def test_list_no_filter(self, mock_db, admin_user):
        ds = _make_ds_mock()
        count_r = MagicMock()
        count_r.scalar = MagicMock(return_value=1)
        rows_r = _scalars_result([ds])
        mock_db.execute = AsyncMock(side_effect=[count_r, rows_r])
        client = _make_client(mock_db, admin_user)
        resp = client.get("/gg-datasources/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1

    @pytest.mark.unit
    def test_list_filter_by_channel(self, mock_db, admin_user):
        ds = _make_ds_mock()
        count_r = MagicMock()
        count_r.scalar = MagicMock(return_value=1)
        rows_r = _scalars_result([ds])
        mock_db.execute = AsyncMock(side_effect=[count_r, rows_r])
        client = _make_client(mock_db, admin_user)
        resp = client.get(f"/gg-datasources/?channel_id={_CH_ID}")
        assert resp.status_code == 200

    @pytest.mark.unit
    def test_list_filter_by_workspace(self, mock_db, admin_user):
        ds = _make_ds_mock(level="workspace", workspace_id=uuid.UUID(_WS_ID), channel_id=None)
        count_r = MagicMock()
        count_r.scalar = MagicMock(return_value=1)
        rows_r = _scalars_result([ds])
        mock_db.execute = AsyncMock(side_effect=[count_r, rows_r])
        client = _make_client(mock_db, admin_user)
        resp = client.get(f"/gg-datasources/?workspace_id={_WS_ID}")
        assert resp.status_code == 200

    @pytest.mark.unit
    def test_list_filter_by_thread(self, mock_db, admin_user):
        ds = _make_ds_mock(level="thread", thread_id=uuid.UUID(_TH_ID), channel_id=None)
        count_r = MagicMock()
        count_r.scalar = MagicMock(return_value=1)
        rows_r = _scalars_result([ds])
        mock_db.execute = AsyncMock(side_effect=[count_r, rows_r])
        client = _make_client(mock_db, admin_user)
        resp = client.get(f"/gg-datasources/?thread_id={_TH_ID}")
        assert resp.status_code == 200

    @pytest.mark.unit
    def test_list_filter_by_message(self, mock_db, admin_user):
        ds = _make_ds_mock(level="message", message_id=uuid.UUID(_MSG_ID), channel_id=None)
        count_r = MagicMock()
        count_r.scalar = MagicMock(return_value=1)
        rows_r = _scalars_result([ds])
        mock_db.execute = AsyncMock(side_effect=[count_r, rows_r])
        client = _make_client(mock_db, admin_user)
        resp = client.get(f"/gg-datasources/?message_id={_MSG_ID}")
        assert resp.status_code == 200

    @pytest.mark.unit
    def test_list_pagination(self, mock_db, admin_user):
        count_r = MagicMock()
        count_r.scalar = MagicMock(return_value=0)
        rows_r = _scalars_result([])
        mock_db.execute = AsyncMock(side_effect=[count_r, rows_r])
        client = _make_client(mock_db, admin_user)
        resp = client.get("/gg-datasources/?page=2&page_size=10")
        assert resp.status_code == 200
        data = resp.json()
        assert data["page"] == 2
        assert data["page_size"] == 10


class TestGetDatasource:
    @pytest.mark.unit
    def test_get_found(self, mock_db, admin_user):
        ds = _make_ds_mock()
        mock_db.execute = AsyncMock(return_value=_scalar(ds))
        client = _make_client(mock_db, admin_user)
        resp = client.get(f"/gg-datasources/{_DS_ID}")
        assert resp.status_code == 200
        assert resp.json()["id"] == _DS_ID

    @pytest.mark.unit
    def test_get_not_found_returns_404(self, mock_db, admin_user):
        mock_db.execute = AsyncMock(return_value=_scalar(None))
        client = _make_client(mock_db, admin_user)
        resp = client.get(f"/gg-datasources/{_DS_ID}")
        assert resp.status_code == 404

    @pytest.mark.unit
    def test_get_channel_level_datasource(self, mock_db, admin_user):
        ds = _make_ds_mock(level="channel")
        mock_db.execute = AsyncMock(return_value=_scalar(ds))
        client = _make_client(mock_db, admin_user)
        resp = client.get(f"/gg-datasources/{_DS_ID}")
        assert resp.status_code == 200
        assert resp.json()["level"] == "channel"

    @pytest.mark.unit
    def test_get_workspace_level_datasource(self, mock_db, admin_user):
        ds = _make_ds_mock(level="workspace", workspace_id=uuid.UUID(_WS_ID), channel_id=None)
        mock_db.execute = AsyncMock(return_value=_scalar(ds))
        client = _make_client(mock_db, admin_user)
        resp = client.get(f"/gg-datasources/{_DS_ID}")
        assert resp.status_code == 200
        assert resp.json()["level"] == "workspace"

    @pytest.mark.unit
    def test_get_thread_level_datasource(self, mock_db, admin_user):
        ds = _make_ds_mock(level="thread", thread_id=uuid.UUID(_TH_ID), channel_id=None)
        mock_db.execute = AsyncMock(return_value=_scalar(ds))
        client = _make_client(mock_db, admin_user)
        resp = client.get(f"/gg-datasources/{_DS_ID}")
        assert resp.status_code == 200
        assert resp.json()["level"] == "thread"


class TestGetEmbeddingStatus:
    @pytest.mark.unit
    def test_channel_scope_returns_status(self, mock_db, admin_user):
        ds = _make_ds_mock(is_embedding_required=True, embedding_status=2)
        mock_db.execute = AsyncMock(return_value=_scalars_result([ds]))
        client = _make_client(mock_db, admin_user)
        resp = client.get(f"/gg-datasources/embedding-status/channel/{_CH_ID}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["scope_level"] == "channel"

    @pytest.mark.unit
    def test_workspace_scope_works(self, mock_db, admin_user):
        ds = _make_ds_mock(level="workspace", workspace_id=uuid.UUID(_WS_ID), channel_id=None,
                           embedding_status=0)
        mock_db.execute = AsyncMock(return_value=_scalars_result([ds]))
        client = _make_client(mock_db, admin_user)
        resp = client.get(f"/gg-datasources/embedding-status/workspace/{_WS_ID}")
        assert resp.status_code == 200
        assert resp.json()["scope_level"] == "workspace"

    @pytest.mark.unit
    def test_thread_scope_works(self, mock_db, admin_user):
        mock_db.execute = AsyncMock(return_value=_scalars_result([]))
        client = _make_client(mock_db, admin_user)
        resp = client.get(f"/gg-datasources/embedding-status/thread/{_TH_ID}")
        assert resp.status_code == 200
        assert resp.json()["scope_level"] == "thread"

    @pytest.mark.unit
    def test_message_scope_works(self, mock_db, admin_user):
        mock_db.execute = AsyncMock(return_value=_scalars_result([]))
        client = _make_client(mock_db, admin_user)
        resp = client.get(f"/gg-datasources/embedding-status/message/{_MSG_ID}")
        assert resp.status_code == 200
        assert resp.json()["scope_level"] == "message"

    @pytest.mark.unit
    def test_invalid_scope_level_returns_400(self, mock_db, admin_user):
        client = _make_client(mock_db, admin_user)
        resp = client.get(f"/gg-datasources/embedding-status/company/{_WS_ID}")
        assert resp.status_code == 400

    @pytest.mark.unit
    def test_embedding_required_count(self, mock_db, admin_user):
        ds1 = _make_ds_mock(is_embedding_required=True, embedding_status=1)
        ds2 = _make_ds_mock(is_embedding_required=True, embedding_status=2)
        ds3 = _make_ds_mock(is_embedding_required=False, embedding_status=0)
        mock_db.execute = AsyncMock(return_value=_scalars_result([ds1, ds2, ds3]))
        client = _make_client(mock_db, admin_user)
        resp = client.get(f"/gg-datasources/embedding-status/channel/{_CH_ID}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["embedding_required"] == 2
        assert data["total_datasources"] == 3


class TestEmbeddingWebhook:
    @pytest.mark.unit
    def test_webhook_success_updates_status(self, mock_db, admin_user):
        vault_uid = str(uuid.uuid4())
        ds = _make_ds_mock(vault_unique_id=uuid.UUID(vault_uid), embedding_status=0)
        mock_db.execute = AsyncMock(return_value=_scalars_result([ds]))
        client = _make_client(mock_db, admin_user)
        resp = client.post(
            "/gg-datasources/embedding/webhook",
            json={"vaultUniqueIds": [vault_uid], "status": "success"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["processed_count"] == 1
        assert ds.embedding_status == 2

    @pytest.mark.unit
    def test_webhook_failed_status(self, mock_db, admin_user):
        vault_uid = str(uuid.uuid4())
        ds = _make_ds_mock(vault_unique_id=uuid.UUID(vault_uid), embedding_status=1)
        mock_db.execute = AsyncMock(return_value=_scalars_result([ds]))
        client = _make_client(mock_db, admin_user)
        resp = client.post(
            "/gg-datasources/embedding/webhook",
            json={"vaultUniqueIds": [vault_uid], "status": "failed"},
        )
        assert resp.status_code == 200
        assert ds.embedding_status == 3

    @pytest.mark.unit
    def test_webhook_empty_ids(self, mock_db, admin_user):
        client = _make_client(mock_db, admin_user)
        resp = client.post(
            "/gg-datasources/embedding/webhook",
            json={"vaultUniqueIds": [], "status": "success"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["processed_count"] == 0

    @pytest.mark.unit
    def test_webhook_sets_error_message_on_failed(self, mock_db, admin_user):
        vault_uid = str(uuid.uuid4())
        ds = _make_ds_mock(vault_unique_id=uuid.UUID(vault_uid), embedding_status=1)
        mock_db.execute = AsyncMock(return_value=_scalars_result([ds]))
        client = _make_client(mock_db, admin_user)
        resp = client.post(
            "/gg-datasources/embedding/webhook",
            json={"vaultUniqueIds": [vault_uid], "status": "failed", "message": "OOM error"},
        )
        assert resp.status_code == 200
        assert ds.error_message == "OOM error"

    @pytest.mark.unit
    def test_webhook_clears_error_message_on_success(self, mock_db, admin_user):
        vault_uid = str(uuid.uuid4())
        ds = _make_ds_mock(vault_unique_id=uuid.UUID(vault_uid), embedding_status=3,
                           error_message="previous error")
        mock_db.execute = AsyncMock(return_value=_scalars_result([ds]))
        client = _make_client(mock_db, admin_user)
        resp = client.post(
            "/gg-datasources/embedding/webhook",
            json={"vaultUniqueIds": [vault_uid], "status": "success"},
        )
        assert resp.status_code == 200
        assert ds.error_message is None


class TestRegenerateEmbedding:
    @pytest.mark.unit
    def test_regenerate_success(self, mock_db, admin_user):
        ds = _make_ds_mock(
            added_by=uuid.UUID(_USER_ID),
            vault_unique_id=uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
        )
        mock_db.execute = AsyncMock(return_value=_scalar(ds))
        with patch(
            "app.routes.gg_datasources.ml_service.request_embedding_processing",
            new=AsyncMock(return_value=None),
        ):
            client = _make_client(mock_db, admin_user)
            resp = client.post(f"/gg-datasources/embedding/regenerate/{_DS_ID}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["embedding_status"] == 1

    @pytest.mark.unit
    def test_regenerate_not_found_returns_404(self, mock_db, admin_user):
        mock_db.execute = AsyncMock(return_value=_scalar(None))
        client = _make_client(mock_db, admin_user)
        resp = client.post(f"/gg-datasources/embedding/regenerate/{_DS_ID}")
        assert resp.status_code == 404

    @pytest.mark.unit
    def test_regenerate_no_vault_returns_400(self, mock_db, admin_user):
        ds = _make_ds_mock(added_by=uuid.UUID(_USER_ID), vault_unique_id=None)
        mock_db.execute = AsyncMock(return_value=_scalar(ds))
        client = _make_client(mock_db, admin_user)
        resp = client.post(f"/gg-datasources/embedding/regenerate/{_DS_ID}")
        assert resp.status_code == 400

    @pytest.mark.unit
    def test_regenerate_wrong_user_returns_403(self, mock_db, admin_user):
        ds = _make_ds_mock(
            added_by=uuid.UUID("ffffffff-ffff-ffff-ffff-ffffffffffff"),
            vault_unique_id=uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
        )
        mock_db.execute = AsyncMock(return_value=_scalar(ds))
        client = _make_client(mock_db, admin_user)
        resp = client.post(f"/gg-datasources/embedding/regenerate/{_DS_ID}")
        assert resp.status_code == 403

    @pytest.mark.unit
    def test_regenerate_ml_failure_returns_failed_status(self, mock_db, admin_user):
        ds = _make_ds_mock(
            added_by=uuid.UUID(_USER_ID),
            vault_unique_id=uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
        )
        mock_db.execute = AsyncMock(return_value=_scalar(ds))
        with patch(
            "app.routes.gg_datasources.ml_service.request_embedding_processing",
            new=AsyncMock(side_effect=Exception("ML service timeout")),
        ):
            client = _make_client(mock_db, admin_user)
            resp = client.post(f"/gg-datasources/embedding/regenerate/{_DS_ID}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert data["embedding_status"] == 3


class TestProcessDatasource:
    @pytest.mark.unit
    def test_process_success(self, mock_db, admin_user):
        ds = _make_ds_mock()
        mock_db.execute = AsyncMock(return_value=_scalar(ds))
        client = _make_client(mock_db, admin_user)
        resp = client.post(
            "/gg-datasources/process",
            json={"datasource_id": _DS_ID},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["datasource_id"] == _DS_ID
        assert data["status"] == "processing_started"

    @pytest.mark.unit
    def test_process_not_found_returns_404(self, mock_db, admin_user):
        mock_db.execute = AsyncMock(return_value=_scalar(None))
        client = _make_client(mock_db, admin_user)
        resp = client.post(
            "/gg-datasources/process",
            json={"datasource_id": _DS_ID},
        )
        assert resp.status_code == 404

    @pytest.mark.unit
    def test_process_missing_datasource_id_returns_422(self, mock_db, admin_user):
        client = _make_client(mock_db, admin_user)
        resp = client.post(
            "/gg-datasources/process",
            json={},
        )
        assert resp.status_code == 422


class TestBulkConnection:
    @pytest.mark.unit
    def test_bulk_connect_success(self, mock_db, admin_user):
        ds = _make_ds_mock(is_connected=False)
        mock_db.execute = AsyncMock(return_value=_scalars_result([ds]))
        client = _make_client(mock_db, admin_user)
        resp = client.post(
            "/gg-datasources/bulk-connection",
            json={"datasource_ids": [_DS_ID], "action": "connect"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_successful"] == 1
        assert data["total_failed"] == 0

    @pytest.mark.unit
    def test_bulk_disconnect_success(self, mock_db, admin_user):
        ds = _make_ds_mock(is_connected=True)
        mock_db.execute = AsyncMock(return_value=_scalars_result([ds]))
        client = _make_client(mock_db, admin_user)
        resp = client.post(
            "/gg-datasources/bulk-connection",
            json={"datasource_ids": [_DS_ID], "action": "disconnect"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_successful"] == 1

    @pytest.mark.unit
    def test_bulk_connect_already_connected_goes_to_failed(self, mock_db, admin_user):
        ds = _make_ds_mock(is_connected=True)
        mock_db.execute = AsyncMock(return_value=_scalars_result([ds]))
        client = _make_client(mock_db, admin_user)
        resp = client.post(
            "/gg-datasources/bulk-connection",
            json={"datasource_ids": [_DS_ID], "action": "connect"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_failed"] == 1
        assert data["total_successful"] == 0

    @pytest.mark.unit
    def test_bulk_connection_missing_ids_returns_404(self, mock_db, admin_user):
        mock_db.execute = AsyncMock(return_value=_scalars_result([]))
        client = _make_client(mock_db, admin_user)
        resp = client.post(
            "/gg-datasources/bulk-connection",
            json={"datasource_ids": [_DS_ID], "action": "connect"},
        )
        assert resp.status_code == 404

    @pytest.mark.unit
    def test_bulk_connection_invalid_action_returns_422(self, mock_db, admin_user):
        client = _make_client(mock_db, admin_user)
        resp = client.post(
            "/gg-datasources/bulk-connection",
            json={"datasource_ids": [_DS_ID], "action": "delete"},
        )
        assert resp.status_code == 422


class TestUpdateDatasource:
    @pytest.mark.unit
    def test_update_name(self, mock_db, admin_user):
        ds = _make_ds_mock(name="Old Name")
        mock_db.execute = AsyncMock(return_value=_scalar(ds))

        async def _refresh(obj):
            pass

        mock_db.refresh = AsyncMock(side_effect=_refresh)
        client = _make_client(mock_db, admin_user)
        resp = client.put(
            f"/gg-datasources/{_DS_ID}",
            json={"name": "New Name"},
        )
        assert resp.status_code == 200

    @pytest.mark.unit
    def test_update_storage_type(self, mock_db, admin_user):
        ds = _make_ds_mock(storage_type="local")
        mock_db.execute = AsyncMock(return_value=_scalar(ds))

        async def _refresh(obj):
            pass

        mock_db.refresh = AsyncMock(side_effect=_refresh)
        client = _make_client(mock_db, admin_user)
        resp = client.put(
            f"/gg-datasources/{_DS_ID}",
            json={"storage_type": "cloud"},
        )
        assert resp.status_code == 200

    @pytest.mark.unit
    def test_update_not_found_returns_404(self, mock_db, admin_user):
        mock_db.execute = AsyncMock(return_value=_scalar(None))
        client = _make_client(mock_db, admin_user)
        resp = client.put(
            f"/gg-datasources/{_DS_ID}",
            json={"name": "New Name"},
        )
        assert resp.status_code == 404

    @pytest.mark.unit
    def test_update_sets_updated_at(self, mock_db, admin_user):
        ds = _make_ds_mock()
        mock_db.execute = AsyncMock(return_value=_scalar(ds))

        async def _refresh(obj):
            pass

        mock_db.refresh = AsyncMock(side_effect=_refresh)
        client = _make_client(mock_db, admin_user)
        resp = client.put(
            f"/gg-datasources/{_DS_ID}",
            json={"name": "Updated"},
        )
        assert resp.status_code == 200
        assert ds.updated_at is not None


class TestDeleteDatasource:
    @pytest.mark.unit
    def test_delete_success(self, mock_db, admin_user):
        ds = _make_ds_mock(is_active=True)
        mock_db.execute = AsyncMock(return_value=_scalar(ds))
        client = _make_client(mock_db, admin_user)
        resp = client.delete(f"/gg-datasources/{_DS_ID}")
        assert resp.status_code == 204
        assert ds.is_active is False

    @pytest.mark.unit
    def test_delete_not_found_returns_404(self, mock_db, admin_user):
        mock_db.execute = AsyncMock(return_value=_scalar(None))
        client = _make_client(mock_db, admin_user)
        resp = client.delete(f"/gg-datasources/{_DS_ID}")
        assert resp.status_code == 404

    @pytest.mark.unit
    def test_delete_is_soft_delete(self, mock_db, admin_user):
        ds = _make_ds_mock(is_active=True)
        mock_db.execute = AsyncMock(return_value=_scalar(ds))
        client = _make_client(mock_db, admin_user)
        client.delete(f"/gg-datasources/{_DS_ID}")
        mock_db.delete.assert_not_called()


class TestUpdateProcessingStatus:
    @pytest.mark.unit
    def test_update_status_to_completed(self, mock_db, admin_user):
        ds = _make_ds_mock(processing_status="pending")
        mock_db.execute = AsyncMock(return_value=_scalar(ds))

        async def _refresh(obj):
            pass

        mock_db.refresh = AsyncMock(side_effect=_refresh)
        client = _make_client(mock_db, admin_user)
        resp = client.put(
            f"/gg-datasources/{_DS_ID}/status",
            json={"processing_status": "completed", "is_processed": True},
        )
        assert resp.status_code == 200
        assert ds.processing_status == "completed"
        assert ds.is_processed is True

    @pytest.mark.unit
    def test_update_status_to_failed(self, mock_db, admin_user):
        ds = _make_ds_mock(processing_status="processing")
        mock_db.execute = AsyncMock(return_value=_scalar(ds))

        async def _refresh(obj):
            pass

        mock_db.refresh = AsyncMock(side_effect=_refresh)
        client = _make_client(mock_db, admin_user)
        resp = client.put(
            f"/gg-datasources/{_DS_ID}/status",
            json={"processing_status": "failed", "error_message": "Out of memory"},
        )
        assert resp.status_code == 200
        assert ds.error_message == "Out of memory"

    @pytest.mark.unit
    def test_update_embedding_status(self, mock_db, admin_user):
        ds = _make_ds_mock(embedding_status=1)
        mock_db.execute = AsyncMock(return_value=_scalar(ds))

        async def _refresh(obj):
            pass

        mock_db.refresh = AsyncMock(side_effect=_refresh)
        client = _make_client(mock_db, admin_user)
        resp = client.put(
            f"/gg-datasources/{_DS_ID}/status",
            json={"embedding_status": 2, "record_count": 42},
        )
        assert resp.status_code == 200
        assert ds.embedding_status == 2
        assert ds.record_count == 42

    @pytest.mark.unit
    def test_update_status_not_found_returns_404(self, mock_db, admin_user):
        mock_db.execute = AsyncMock(return_value=_scalar(None))
        client = _make_client(mock_db, admin_user)
        resp = client.put(
            f"/gg-datasources/{_DS_ID}/status",
            json={"processing_status": "completed"},
        )
        assert resp.status_code == 404

    @pytest.mark.unit
    def test_update_status_sets_last_processed_at_on_completed(self, mock_db, admin_user):
        ds = _make_ds_mock(processing_status="processing", last_processed_at=None)
        mock_db.execute = AsyncMock(return_value=_scalar(ds))

        async def _refresh(obj):
            pass

        mock_db.refresh = AsyncMock(side_effect=_refresh)
        client = _make_client(mock_db, admin_user)
        resp = client.put(
            f"/gg-datasources/{_DS_ID}/status",
            json={"processing_status": "completed"},
        )
        assert resp.status_code == 200
        assert ds.last_processed_at is not None


class TestConnectDatasource:
    @pytest.mark.unit
    def test_connect_success(self, mock_db, admin_user):
        ds = _make_ds_mock(is_connected=False)
        mock_db.execute = AsyncMock(return_value=_scalar(ds))

        async def _refresh(obj):
            pass

        mock_db.refresh = AsyncMock(side_effect=_refresh)
        client = _make_client(mock_db, admin_user)
        resp = client.post(f"/gg-datasources/{_DS_ID}/connect")
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_connected"] is True

    @pytest.mark.unit
    def test_connect_not_found_returns_404(self, mock_db, admin_user):
        mock_db.execute = AsyncMock(return_value=_scalar(None))
        client = _make_client(mock_db, admin_user)
        resp = client.post(f"/gg-datasources/{_DS_ID}/connect")
        assert resp.status_code == 404

    @pytest.mark.unit
    def test_connect_already_connected_returns_400(self, mock_db, admin_user):
        ds = _make_ds_mock(is_connected=True)
        mock_db.execute = AsyncMock(return_value=_scalar(ds))
        client = _make_client(mock_db, admin_user)
        resp = client.post(f"/gg-datasources/{_DS_ID}/connect")
        assert resp.status_code == 400

    @pytest.mark.unit
    def test_connect_sets_flag_true(self, mock_db, admin_user):
        ds = _make_ds_mock(is_connected=False)
        mock_db.execute = AsyncMock(return_value=_scalar(ds))

        async def _refresh(obj):
            pass

        mock_db.refresh = AsyncMock(side_effect=_refresh)
        client = _make_client(mock_db, admin_user)
        client.post(f"/gg-datasources/{_DS_ID}/connect")
        assert ds.is_connected is True


class TestDisconnectDatasource:
    @pytest.mark.unit
    def test_disconnect_success(self, mock_db, admin_user):
        ds = _make_ds_mock(is_connected=True)
        mock_db.execute = AsyncMock(return_value=_scalar(ds))

        async def _refresh(obj):
            pass

        mock_db.refresh = AsyncMock(side_effect=_refresh)
        client = _make_client(mock_db, admin_user)
        resp = client.post(f"/gg-datasources/{_DS_ID}/disconnect")
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_connected"] is False

    @pytest.mark.unit
    def test_disconnect_not_found_returns_404(self, mock_db, admin_user):
        mock_db.execute = AsyncMock(return_value=_scalar(None))
        client = _make_client(mock_db, admin_user)
        resp = client.post(f"/gg-datasources/{_DS_ID}/disconnect")
        assert resp.status_code == 404

    @pytest.mark.unit
    def test_disconnect_already_disconnected_returns_400(self, mock_db, admin_user):
        ds = _make_ds_mock(is_connected=False)
        mock_db.execute = AsyncMock(return_value=_scalar(ds))
        client = _make_client(mock_db, admin_user)
        resp = client.post(f"/gg-datasources/{_DS_ID}/disconnect")
        assert resp.status_code == 400

    @pytest.mark.unit
    def test_disconnect_sets_flag_false(self, mock_db, admin_user):
        ds = _make_ds_mock(is_connected=True)
        mock_db.execute = AsyncMock(return_value=_scalar(ds))

        async def _refresh(obj):
            pass

        mock_db.refresh = AsyncMock(side_effect=_refresh)
        client = _make_client(mock_db, admin_user)
        client.post(f"/gg-datasources/{_DS_ID}/disconnect")
        assert ds.is_connected is False


class TestConnectionStatus:
    @pytest.mark.unit
    def test_connected_status(self, mock_db, admin_user):
        ds = _make_ds_mock(is_connected=True)
        mock_db.execute = AsyncMock(return_value=_scalar(ds))
        client = _make_client(mock_db, admin_user)
        resp = client.get(f"/gg-datasources/{_DS_ID}/connection-status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_connected"] is True
        assert "connected" in data["message"].lower()

    @pytest.mark.unit
    def test_disconnected_status(self, mock_db, admin_user):
        ds = _make_ds_mock(is_connected=False)
        mock_db.execute = AsyncMock(return_value=_scalar(ds))
        client = _make_client(mock_db, admin_user)
        resp = client.get(f"/gg-datasources/{_DS_ID}/connection-status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_connected"] is False
        assert "disconnected" in data["message"].lower()

    @pytest.mark.unit
    def test_not_found_returns_404(self, mock_db, admin_user):
        mock_db.execute = AsyncMock(return_value=_scalar(None))
        client = _make_client(mock_db, admin_user)
        resp = client.get(f"/gg-datasources/{_DS_ID}/connection-status")
        assert resp.status_code == 404


class TestDownloadDatasource:
    @pytest.mark.unit
    def test_download_local_file(self, mock_db, admin_user):
        ds = _make_ds_mock(
            config={"file_path": "company/2025/test.pdf"},
            storage_type="local",
            filename="test.pdf",
            file_type="application/pdf",
        )
        mock_db.execute = AsyncMock(return_value=_scalar(ds))
        storage_service = MagicMock()
        storage_service.download_file = AsyncMock(return_value=b"%PDF-1.4 content")
        with patch(
            "app.routes.gg_datasources.get_file_storage_service",
            return_value=storage_service,
        ):
            client = _make_client(mock_db, admin_user)
            resp = client.get(f"/gg-datasources/{_DS_ID}/download")
        assert resp.status_code == 200
        assert resp.content == b"%PDF-1.4 content"

    @pytest.mark.unit
    def test_download_inline_view(self, mock_db, admin_user):
        ds = _make_ds_mock(
            config={"file_path": "company/2025/test.pdf"},
            storage_type="local",
            filename="test.pdf",
            file_type="application/pdf",
        )
        mock_db.execute = AsyncMock(return_value=_scalar(ds))
        storage_service = MagicMock()
        storage_service.download_file = AsyncMock(return_value=b"content")
        with patch(
            "app.routes.gg_datasources.get_file_storage_service",
            return_value=storage_service,
        ):
            client = _make_client(mock_db, admin_user)
            resp = client.get(f"/gg-datasources/{_DS_ID}/download?view=true")
        assert resp.status_code == 200
        assert "inline" in resp.headers.get("content-disposition", "")

    @pytest.mark.unit
    def test_download_external_url_redirects(self, mock_db, admin_user):
        ds = _make_ds_mock(
            config={},
            file_url="https://external.storage/file.pdf",
            storage_type="local",
        )
        mock_db.execute = AsyncMock(return_value=_scalar(ds))
        client = _make_client(mock_db, admin_user)
        resp = client.get(f"/gg-datasources/{_DS_ID}/download", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["location"] == "https://external.storage/file.pdf"

    @pytest.mark.unit
    def test_download_external_url_json_request(self, mock_db, admin_user):
        ds = _make_ds_mock(
            config={},
            file_url="https://external.storage/file.pdf",
            storage_type="local",
        )
        mock_db.execute = AsyncMock(return_value=_scalar(ds))
        client = _make_client(mock_db, admin_user)
        resp = client.get(
            f"/gg-datasources/{_DS_ID}/download",
            headers={"Accept": "application/json"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "url" in data

    @pytest.mark.unit
    def test_download_database_datasource_returns_404(self, mock_db, admin_user):
        ds = _make_ds_mock(
            config={},
            file_url=None,
            storage_type="database",
        )
        mock_db.execute = AsyncMock(return_value=_scalar(ds))
        client = _make_client(mock_db, admin_user)
        resp = client.get(f"/gg-datasources/{_DS_ID}/download")
        assert resp.status_code == 404

    @pytest.mark.unit
    def test_download_not_found_returns_404(self, mock_db, admin_user):
        mock_db.execute = AsyncMock(return_value=_scalar(None))
        client = _make_client(mock_db, admin_user)
        resp = client.get(f"/gg-datasources/{_DS_ID}/download")
        assert resp.status_code == 404

    @pytest.mark.unit
    def test_download_no_file_path_no_url_returns_404(self, mock_db, admin_user):
        ds = _make_ds_mock(
            config={},
            file_url=None,
            storage_type="local",
            provider=None,
        )
        mock_db.execute = AsyncMock(return_value=_scalar(ds))
        client = _make_client(mock_db, admin_user)
        resp = client.get(f"/gg-datasources/{_DS_ID}/download")
        assert resp.status_code == 404

    @pytest.mark.unit
    def test_download_storage_failure_returns_404(self, mock_db, admin_user):
        ds = _make_ds_mock(
            config={"file_path": "company/2025/test.pdf"},
            storage_type="local",
            filename="test.pdf",
        )
        mock_db.execute = AsyncMock(return_value=_scalar(ds))
        storage_service = MagicMock()
        storage_service.download_file = AsyncMock(side_effect=Exception("S3 connection failed"))
        with patch(
            "app.routes.gg_datasources.get_file_storage_service",
            return_value=storage_service,
        ):
            client = _make_client(mock_db, admin_user)
            resp = client.get(f"/gg-datasources/{_DS_ID}/download")
        assert resp.status_code == 404


# ===========================================================================
# Media-type Helper Tests
# ===========================================================================


class TestMediaTypeHelpers:
    """Unit tests for helper functions in gg_datasources.py — no DB needed."""

    from app.routes.gg_datasources import (
        _get_media_type,
        _get_storage_file_path,
        _get_external_view_url,
        _get_google_drive_file_id,
    )

    @pytest.mark.unit
    def test_get_media_type_from_file_type(self):
        from app.routes.gg_datasources import _get_media_type
        ds = _make_ds_mock(file_type="text/csv", filename="data.csv")
        assert _get_media_type(ds) == "text/csv"

    @pytest.mark.unit
    def test_get_media_type_from_extension(self):
        from app.routes.gg_datasources import _get_media_type
        ds = _make_ds_mock(file_type=None, filename="report.xlsx")
        result = _get_media_type(ds)
        assert "spreadsheet" in result or result == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    @pytest.mark.unit
    def test_get_media_type_pdf(self):
        from app.routes.gg_datasources import _get_media_type
        ds = _make_ds_mock(file_type=None, filename="doc.pdf")
        assert _get_media_type(ds) == "application/pdf"

    @pytest.mark.unit
    def test_get_media_type_unknown_fallback(self):
        from app.routes.gg_datasources import _get_media_type
        ds = _make_ds_mock(file_type=None, filename="data.xyz")
        assert _get_media_type(ds) == "application/octet-stream"

    @pytest.mark.unit
    def test_get_storage_file_path_from_config(self):
        from app.routes.gg_datasources import _get_storage_file_path
        ds = _make_ds_mock(config={"file_path": "company/2025/test.csv"})
        assert _get_storage_file_path(ds) == "company/2025/test.csv"

    @pytest.mark.unit
    def test_get_storage_file_path_none(self):
        from app.routes.gg_datasources import _get_storage_file_path
        ds = _make_ds_mock(config={}, datasource_metadata={})
        assert _get_storage_file_path(ds) is None

    @pytest.mark.unit
    def test_get_external_view_url_from_file_url(self):
        from app.routes.gg_datasources import _get_external_view_url
        ds = _make_ds_mock(file_url="https://drive.google.com/file/d/abc/view", config={})
        assert _get_external_view_url(ds) == "https://drive.google.com/file/d/abc/view"

    @pytest.mark.unit
    def test_get_external_view_url_none(self):
        from app.routes.gg_datasources import _get_external_view_url
        ds = _make_ds_mock(file_url=None, config={}, app_type=None)
        assert _get_external_view_url(ds) is None

    @pytest.mark.unit
    def test_get_google_drive_url_from_file_id(self):
        from app.routes.gg_datasources import _get_external_view_url
        ds = _make_ds_mock(
            file_url=None,
            app_type="google_drive",
            config={"file_id": "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs"},
        )
        url = _get_external_view_url(ds)
        assert url is not None
        assert "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs" in url
