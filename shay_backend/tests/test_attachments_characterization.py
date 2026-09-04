"""
Golden-master / characterization tests for app/routes/attachments.py.

Purpose: attachments.py is 1,096 lines with 12 endpoints and had ZERO
existing test coverage before this file. It is about to be split into a
package (see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item
2). Before the split, we capture the CURRENT observable behavior of every
endpoint so the split can be verified to change nothing.

These are characterization tests, not "correctness" tests: assertions match
what the code actually does today, bugs included. Pattern follows
tests/test_channels_characterization.py:
- FastAPI TestClient with `app.include_router(router, prefix=...)`.
- `app.dependency_overrides[get_db] = lambda: mock_db`.
- MagicMock/AsyncMock for services; no real DB, no real HTTP.
- `asyncio.run()` is not needed here — TestClient drives the event loop.

Do not modify app/routes/attachments.py from this file's tests.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _make_client(mock_db):
    from app.core.database import get_db
    from app.routes.attachments import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/attachments")
    app.dependency_overrides[get_db] = lambda: mock_db
    return TestClient(app, raise_server_exceptions=False)


def _auth(user, module):
    """attachments.py calls get_current_user_required(request) — single arg,
    no db — unlike gg_datasources' get_current_user_required(request, db).

    app/routes/attachments.py was split into a package (Raven style
    compliance, Phase 5a item 2); each submodule imports
    get_current_user_required itself, so the patch target must be the exact
    submodule that owns the endpoint under test, not the re-exporting
    package (app.routes.attachments.get_current_user_required would not
    affect a submodule's own bound reference)."""
    return patch(f"app.routes.attachments.{module}.get_current_user_required", new=AsyncMock(return_value=user))


class _FakeResult:
    def __init__(self, scalar_one_or_none=None, all_=None, scalar_val=None, rows=None):
        self._son = scalar_one_or_none
        self._all = all_ if all_ is not None else []
        self._scalar_val = scalar_val
        self._rows = rows if rows is not None else []

    def scalar_one_or_none(self):
        return self._son

    def scalars(self):
        return self

    def all(self):
        return self._all

    def scalar(self):
        return self._scalar_val

    def __iter__(self):
        return iter(self._rows)


def _scalar(obj):
    return _FakeResult(scalar_one_or_none=obj)


_ATT_ID = "att-0001"
_CH_ID = "channel-0001"
_TASK_ID = "task-0001"
_WS_ID = "workspace-0001"


def _make_channel(accessible=True):
    ch = MagicMock()
    ch.id = _CH_ID
    ch.workspace_id = _WS_ID
    ch.is_accessible_by_user = MagicMock(return_value=accessible)
    return ch


def _make_company():
    c = MagicMock()
    c.id = "company-0001"
    c.name = "Test Company"
    return c


def _make_attachment(accessible=True, user_id="user-admin-001"):
    a = MagicMock()
    a.id = _ATT_ID
    a.filename = "abc.csv"
    a.original_filename = "abc.csv"
    a.file_path = "path/to/abc.csv"
    a.file_size = 123
    a.mime_type = "text/csv"
    a.file_extension = ".csv"
    a.message_id = None
    a.task_id = None
    a.channel_id = _CH_ID
    a.workspace_id = _WS_ID
    a.user_id = user_id
    a.is_public = False
    a.is_processed = False
    a.processing_status = "pending"
    a.processing_error = None
    a.content_summary = None
    a.log_entries_count = 0
    a.error_count = 0
    a.warning_count = 0
    a.created_at = datetime(2026, 1, 1)
    a.updated_at = datetime(2026, 1, 1)
    a.can_be_accessed_by_user = MagicMock(return_value=accessible)
    return a


def _make_task(workspace_id=None):
    t = MagicMock()
    t.id = _TASK_ID
    t.workspace_id = workspace_id
    t.channel_id = _CH_ID
    return t


def _make_workspace(accessible=True):
    w = MagicMock()
    w.id = _WS_ID
    w.is_accessible_by_user = MagicMock(return_value=accessible)
    return w


def _fake_storage_service(upload_return=None, download_return=b"filecontent"):
    svc = MagicMock()
    svc.upload_file = AsyncMock(return_value=upload_return or {
        "storage_path": "stored/abc.csv",
        "provider": "local",
        "file_url": "http://local/abc.csv",
    })
    svc.download_file = AsyncMock(return_value=download_return)
    svc.delete_file = AsyncMock(return_value=None)
    return svc


async def _fake_refresh(obj):
    """Mimic the column defaults SQLAlchemy applies on flush (is_processed=False,
    processing_status='pending', counts=0, timestamps=now) — mock_db.refresh is a
    no-op AsyncMock by default, so freshly constructed Attachment() objects in the
    real endpoint code would otherwise keep every un-passed column as None."""
    defaults = {
        "is_processed": False,
        "processing_status": "pending",
        "log_entries_count": 0,
        "error_count": 0,
        "warning_count": 0,
        "created_at": datetime(2026, 1, 1),
        "updated_at": datetime(2026, 1, 1),
    }
    for field, value in defaults.items():
        if getattr(obj, field, None) is None:
            setattr(obj, field, value)


# ---------------------------------------------------------------------------
# POST /upload
# ---------------------------------------------------------------------------

class TestUploadFile:
    @pytest.mark.unit
    def test_upload_success(self, mock_db, admin_user):
        channel = _make_channel()
        company = _make_company()
        mock_db.execute = AsyncMock(side_effect=[_scalar(channel), _scalar(company)])
        mock_db.refresh = AsyncMock(side_effect=_fake_refresh)
        with _auth(admin_user, "upload"), \
             patch("app.routes.attachments.upload.get_file_storage_service", return_value=_fake_storage_service()), \
             patch("app.routes.attachments.upload.audit_log_write", new=AsyncMock()):
            client = _make_client(mock_db)
            resp = client.post(
                "/api/v1/attachments/upload",
                params={"channel_id": _CH_ID},
                files={"file": ("test.csv", b"a,b\n1,2", "text/csv")},
            )
        assert resp.status_code == 200
        assert resp.json()["filename"].endswith(".csv")

    @pytest.mark.unit
    def test_upload_channel_not_found_returns_404(self, mock_db, admin_user):
        mock_db.execute = AsyncMock(return_value=_scalar(None))
        with _auth(admin_user, "upload"):
            client = _make_client(mock_db)
            resp = client.post(
                "/api/v1/attachments/upload",
                params={"channel_id": _CH_ID},
                files={"file": ("test.csv", b"data", "text/csv")},
            )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /
# ---------------------------------------------------------------------------

class TestListAttachments:
    @pytest.mark.unit
    def test_list_success(self, mock_db, admin_user):
        channel = _make_channel()
        att = _make_attachment()
        mock_db.execute = AsyncMock(side_effect=[
            _scalar(channel),
            _FakeResult(all_=[att]),
            _FakeResult(scalar_val=1),
        ])
        with _auth(admin_user, "list"):
            client = _make_client(mock_db)
            resp = client.get("/api/v1/attachments/", params={"channel_id": _CH_ID})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert len(data["attachments"]) == 1

    @pytest.mark.unit
    def test_list_channel_access_denied_returns_403(self, mock_db, admin_user):
        channel = _make_channel(accessible=False)
        mock_db.execute = AsyncMock(return_value=_scalar(channel))
        with _auth(admin_user, "list"):
            client = _make_client(mock_db)
            resp = client.get("/api/v1/attachments/", params={"channel_id": _CH_ID})
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# GET /{attachment_id}
# ---------------------------------------------------------------------------

class TestGetAttachment:
    @pytest.mark.unit
    def test_get_success(self, mock_db, admin_user):
        att = _make_attachment()
        mock_db.execute = AsyncMock(return_value=_scalar(att))
        with _auth(admin_user, "detail"):
            client = _make_client(mock_db)
            resp = client.get(f"/api/v1/attachments/{_ATT_ID}")
        assert resp.status_code == 200
        assert resp.json()["id"] == _ATT_ID

    @pytest.mark.unit
    def test_get_not_found_returns_404(self, mock_db, admin_user):
        mock_db.execute = AsyncMock(return_value=_scalar(None))
        with _auth(admin_user, "detail"):
            client = _make_client(mock_db)
            resp = client.get(f"/api/v1/attachments/{_ATT_ID}")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /{attachment_id}/download
# ---------------------------------------------------------------------------

class TestDownloadAttachment:
    @pytest.mark.unit
    def test_download_success(self, mock_db, admin_user):
        att = _make_attachment()
        mock_db.execute = AsyncMock(return_value=_scalar(att))
        with _auth(admin_user, "detail"), \
             patch("app.routes.attachments.detail.get_file_storage_service", return_value=_fake_storage_service()):
            client = _make_client(mock_db)
            resp = client.get(f"/api/v1/attachments/{_ATT_ID}/download")
        assert resp.status_code == 200
        assert resp.content == b"filecontent"

    @pytest.mark.unit
    def test_download_storage_failure_returns_404(self, mock_db, admin_user):
        att = _make_attachment()
        mock_db.execute = AsyncMock(return_value=_scalar(att))
        svc = _fake_storage_service()
        svc.download_file = AsyncMock(side_effect=Exception("boom"))
        with _auth(admin_user, "detail"), \
             patch("app.routes.attachments.detail.get_file_storage_service", return_value=svc):
            client = _make_client(mock_db)
            resp = client.get(f"/api/v1/attachments/{_ATT_ID}/download")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /{attachment_id}
# ---------------------------------------------------------------------------

class TestDeleteAttachment:
    @pytest.mark.unit
    def test_delete_success(self, mock_db, admin_user):
        att = _make_attachment()
        mock_db.execute = AsyncMock(return_value=_scalar(att))
        mock_db.delete = AsyncMock()
        with _auth(admin_user, "detail"), \
             patch("app.routes.attachments.detail.get_file_storage_service", return_value=_fake_storage_service()), \
             patch("app.routes.attachments.detail.audit_log_write", new=AsyncMock()):
            client = _make_client(mock_db)
            resp = client.delete(f"/api/v1/attachments/{_ATT_ID}")
        assert resp.status_code == 200
        assert resp.json()["message"] == "Attachment deleted successfully"

    @pytest.mark.unit
    def test_delete_access_denied_returns_403(self, mock_db, admin_user):
        att = _make_attachment(accessible=False)
        mock_db.execute = AsyncMock(return_value=_scalar(att))
        with _auth(admin_user, "detail"):
            client = _make_client(mock_db)
            resp = client.delete(f"/api/v1/attachments/{_ATT_ID}")
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# GET /stats/{channel_id}
# ---------------------------------------------------------------------------

class TestAttachmentStats:
    @pytest.mark.unit
    def test_stats_success(self, mock_db, admin_user):
        channel = _make_channel()
        mock_db.execute = AsyncMock(side_effect=[
            _scalar(channel),
            _FakeResult(scalar_val=5),   # total
            _FakeResult(scalar_val=1000),  # size
            _FakeResult(scalar_val=2),   # processed
            _FakeResult(scalar_val=1),   # failed
            _FakeResult(scalar_val=2),   # pending
            _FakeResult(scalar_val=3),   # log files
            _FakeResult(scalar_val=1),   # json files
            _FakeResult(scalar_val=0),   # xml files
        ])
        with _auth(admin_user, "stats"):
            client = _make_client(mock_db)
            resp = client.get(f"/api/v1/attachments/stats/{_CH_ID}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_attachments"] == 5
        assert data["total_size_bytes"] == 1000

    @pytest.mark.unit
    def test_stats_channel_not_found_returns_404(self, mock_db, admin_user):
        mock_db.execute = AsyncMock(return_value=_scalar(None))
        with _auth(admin_user, "stats"):
            client = _make_client(mock_db)
            resp = client.get(f"/api/v1/attachments/stats/{_CH_ID}")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /task/{task_id}/upload
# ---------------------------------------------------------------------------

class TestUploadTaskAttachment:
    @pytest.mark.unit
    def test_upload_success_no_workspace(self, mock_db, admin_user):
        """PRE-EXISTING BUG (characterized, not fixed): the handler builds
        `file_path=storage_info.get("file_path", destination_path)` but only
        ever assigns a local variable named `structured_path` — `destination_path`
        does not exist. Since the real storage service response never contains
        a "file_path" key (it returns "storage_path"), this fallback always
        evaluates and always raises NameError -> 500, on every call, even the
        otherwise-happy path."""
        task = _make_task(workspace_id=None)
        company = _make_company()
        mock_db.execute = AsyncMock(side_effect=[_scalar(task), _scalar(company)])
        mock_db.refresh = AsyncMock(side_effect=_fake_refresh)
        with _auth(admin_user, "task_upload"), \
             patch("app.routes.attachments.task_upload.get_file_storage_service", return_value=_fake_storage_service()):
            client = _make_client(mock_db)
            resp = client.post(
                f"/api/v1/attachments/task/{_TASK_ID}/upload",
                files={"file": ("test.csv", b"data", "text/csv")},
            )
        assert resp.status_code == 500

    @pytest.mark.unit
    def test_upload_task_not_found_returns_404(self, mock_db, admin_user):
        mock_db.execute = AsyncMock(return_value=_scalar(None))
        with _auth(admin_user, "task_upload"):
            client = _make_client(mock_db)
            resp = client.post(
                f"/api/v1/attachments/task/{_TASK_ID}/upload",
                files={"file": ("test.csv", b"data", "text/csv")},
            )
        assert resp.status_code == 404

    @pytest.mark.unit
    def test_upload_invalid_extension_returns_400(self, mock_db, admin_user):
        task = _make_task(workspace_id=None)
        mock_db.execute = AsyncMock(return_value=_scalar(task))
        with _auth(admin_user, "task_upload"):
            client = _make_client(mock_db)
            resp = client.post(
                f"/api/v1/attachments/task/{_TASK_ID}/upload",
                files={"file": ("test.exe", b"data", "application/octet-stream")},
            )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# GET /task/{task_id}/attachments
# ---------------------------------------------------------------------------

class TestGetTaskAttachments:
    @pytest.mark.unit
    def test_list_success(self, mock_db, admin_user):
        task = _make_task(workspace_id=None)
        att = _make_attachment()
        att.task_id = _TASK_ID
        mock_db.execute = AsyncMock(side_effect=[
            _scalar(task),
            _FakeResult(all_=[att]),
            _FakeResult(scalar_val=1),
        ])
        with _auth(admin_user, "task_list"):
            client = _make_client(mock_db)
            resp = client.get(f"/api/v1/attachments/task/{_TASK_ID}/attachments")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    @pytest.mark.unit
    def test_workspace_access_denied_returns_403(self, mock_db, admin_user):
        task = _make_task(workspace_id=_WS_ID)
        workspace = _make_workspace(accessible=False)
        mock_db.execute = AsyncMock(side_effect=[_scalar(task), _scalar(workspace)])
        with _auth(admin_user, "task_list"):
            client = _make_client(mock_db)
            resp = client.get(f"/api/v1/attachments/task/{_TASK_ID}/attachments")
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# GET /task/{task_id}/attachments/stats
# ---------------------------------------------------------------------------

class TestGetTaskAttachmentStats:
    @pytest.mark.unit
    def test_stats_success(self, mock_db, admin_user):
        task = _make_task(workspace_id=None)
        mock_db.execute = AsyncMock(side_effect=[
            _scalar(task),
            _FakeResult(scalar_val=4),
            _FakeResult(scalar_val=800),
            _FakeResult(scalar_val=1),
            _FakeResult(scalar_val=1),
            _FakeResult(scalar_val=2),
            _FakeResult(rows=[(".csv", 3), (".json", 1)]),
        ])
        with _auth(admin_user, "task_stats"):
            client = _make_client(mock_db)
            resp = client.get(f"/api/v1/attachments/task/{_TASK_ID}/attachments/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_attachments"] == 4
        assert data["by_file_type"] == {".csv": 3, ".json": 1}

    @pytest.mark.unit
    def test_task_not_found_returns_404(self, mock_db, admin_user):
        mock_db.execute = AsyncMock(return_value=_scalar(None))
        with _auth(admin_user, "task_stats"):
            client = _make_client(mock_db)
            resp = client.get(f"/api/v1/attachments/task/{_TASK_ID}/attachments/stats")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /task/{task_id}/attachments/{attachment_id}
# ---------------------------------------------------------------------------

class TestDeleteTaskAttachment:
    @pytest.mark.unit
    def test_delete_success_owner(self, mock_db, admin_user):
        task = _make_task(workspace_id=None)
        att = _make_attachment(user_id=admin_user.id)
        mock_db.execute = AsyncMock(side_effect=[_scalar(task), _scalar(att)])
        mock_db.delete = AsyncMock()
        with _auth(admin_user, "task_detail"), \
             patch("app.routes.attachments.task_detail.get_file_storage_service", return_value=_fake_storage_service()):
            client = _make_client(mock_db)
            resp = client.delete(f"/api/v1/attachments/task/{_TASK_ID}/attachments/{_ATT_ID}")
        assert resp.status_code == 200

    @pytest.mark.unit
    def test_delete_not_owner_not_admin_returns_403(self, mock_db, regular_user):
        task = _make_task(workspace_id=None)
        att = _make_attachment(user_id="someone-else")
        mock_db.execute = AsyncMock(side_effect=[_scalar(task), _scalar(att)])
        with _auth(regular_user, "task_detail"):
            client = _make_client(mock_db)
            resp = client.delete(f"/api/v1/attachments/task/{_TASK_ID}/attachments/{_ATT_ID}")
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# PUT /task/{task_id}/attachments/{attachment_id}
# ---------------------------------------------------------------------------

class TestUpdateTaskAttachment:
    @pytest.mark.unit
    def test_update_success(self, mock_db, admin_user):
        task = _make_task(workspace_id=None)
        att = _make_attachment(user_id=admin_user.id)
        att.task_id = _TASK_ID
        mock_db.execute = AsyncMock(side_effect=[_scalar(task), _scalar(att)])
        with _auth(admin_user, "task_detail"):
            client = _make_client(mock_db)
            resp = client.put(
                f"/api/v1/attachments/task/{_TASK_ID}/attachments/{_ATT_ID}",
                json={"is_public": True},
            )
        assert resp.status_code == 200

    @pytest.mark.unit
    def test_update_attachment_not_found_returns_404(self, mock_db, admin_user):
        task = _make_task(workspace_id=None)
        mock_db.execute = AsyncMock(side_effect=[_scalar(task), _scalar(None)])
        with _auth(admin_user, "task_detail"):
            client = _make_client(mock_db)
            resp = client.put(
                f"/api/v1/attachments/task/{_TASK_ID}/attachments/{_ATT_ID}",
                json={"is_public": True},
            )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /task/{task_id}/bulk-upload
# ---------------------------------------------------------------------------

class TestBulkUploadTaskAttachments:
    @pytest.mark.unit
    def test_bulk_upload_success(self, mock_db, admin_user):
        """PRE-EXISTING BUG (characterized, not fixed): same undefined
        `destination_path` name referenced at
        `file_path=storage_info.get("file_path", destination_path)` (see
        TestUploadTaskAttachment.test_upload_success_no_workspace) — every
        call raises NameError inside the per-file loop, which the handler's
        own `except Exception` catches and reports as a 500."""
        task = _make_task(workspace_id=None)
        company = _make_company()
        mock_db.execute = AsyncMock(side_effect=[_scalar(task), _scalar(company)])
        mock_db.add_all = MagicMock()
        mock_db.refresh = AsyncMock(side_effect=_fake_refresh)
        with _auth(admin_user, "task_bulk"), \
             patch("app.routes.attachments.task_bulk.get_file_storage_service", return_value=_fake_storage_service()):
            client = _make_client(mock_db)
            resp = client.post(
                f"/api/v1/attachments/task/{_TASK_ID}/bulk-upload",
                files=[("files", ("a.csv", b"1,2", "text/csv")), ("files", ("b.csv", b"3,4", "text/csv"))],
            )
        assert resp.status_code == 500

    @pytest.mark.unit
    def test_bulk_upload_too_many_files_returns_400(self, mock_db, admin_user):
        with _auth(admin_user, "task_bulk"):
            client = _make_client(mock_db)
            files = [("files", (f"f{i}.csv", b"data", "text/csv")) for i in range(21)]
            resp = client.post(
                f"/api/v1/attachments/task/{_TASK_ID}/bulk-upload",
                files=files,
            )
        assert resp.status_code == 400
