"""
Golden-master / characterization tests for app/routes/template.py.

Purpose: template.py is 881 lines with 9 endpoints and had ZERO existing
test coverage before this file. It is about to be split into a package (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2). Before the
split, we capture the CURRENT observable behavior of every endpoint so the
split can be verified to change nothing.

These are characterization tests, not "correctness" tests: assertions match
what the code actually does today, bugs included. Auth is commented out
throughout template.py ("Authentication removed for testing") — every
endpoint is reachable with no auth header, which these tests reflect as-is.

Unlike attachments.py / gg_datasources.py, most endpoints here do real
filesystem I/O against `settings.TEMPLATE_DIR` rather than pure DB mocks, so
these tests patch `settings.TEMPLATE_DIR` to a pytest tmp_path instead of
mocking the filesystem.

Pattern follows tests/test_channels_characterization.py where DB access is
involved:
- FastAPI TestClient with `app.include_router(router, prefix=...)`.
- `app.dependency_overrides[get_db] = lambda: mock_db`.
- MagicMock/AsyncMock for services; no real DB, no real HTTP.

Do not modify app/routes/template.py from this file's tests.
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
    from app.routes.template import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/template")
    app.dependency_overrides[get_db] = lambda: mock_db
    return TestClient(app, raise_server_exceptions=False)


class _FakeResult:
    def __init__(self, scalar_one_or_none=None, all_=None, scalar_val=None):
        self._son = scalar_one_or_none
        self._all = all_ if all_ is not None else []
        self._scalar_val = scalar_val

    def scalar_one_or_none(self):
        return self._son

    def scalars(self):
        return self

    def all(self):
        return self._all

    def scalar(self):
        return self._scalar_val


def _scalar(obj):
    return _FakeResult(scalar_one_or_none=obj)


async def _fake_refresh(obj):
    """Mimic column defaults SQLAlchemy applies on flush for a freshly
    constructed Template() — mock_db.refresh is a no-op AsyncMock, so an
    un-refreshed object would otherwise keep id/created_datetime/
    updated_datetime as None, which TemplateResponse requires as non-None."""
    if getattr(obj, "id", None) is None:
        obj.id = uuid.uuid4()
    if getattr(obj, "created_datetime", None) is None:
        obj.created_datetime = datetime(2026, 1, 1)
    if getattr(obj, "updated_datetime", None) is None:
        obj.updated_datetime = datetime(2026, 1, 1)


def _make_template(**overrides):
    t = MagicMock()
    t.id = uuid.uuid4()
    t.template_id = "TMPLT_PWD_BASE_ABCD1234"
    t.template_name = "reset.html"
    t.file_path = None
    t.file_size = "10"
    t.additional_config = {}
    t.created_datetime = datetime(2026, 1, 1)
    t.updated_datetime = datetime(2026, 1, 1)
    for k, v in overrides.items():
        setattr(t, k, v)
    return t


# ---------------------------------------------------------------------------
# GET /files
# ---------------------------------------------------------------------------

class TestListTemplateFiles:
    @pytest.mark.unit
    def test_lists_files_success(self, mock_db, tmp_path):
        (tmp_path / "a.html").write_text("<html></html>")
        (tmp_path / "b.txt").write_text("hello")
        (tmp_path / "skip.exe").write_text("nope")
        with patch("app.routes.template.files_list.settings.TEMPLATE_DIR", str(tmp_path)), \
             patch("app.routes.template.files_list.settings.ALLOWED_TEMPLATE_TYPES", [".html", ".txt"]):
            client = _make_client(mock_db)
            resp = client.get("/api/v1/template/files")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_files"] == 2
        names = sorted(f["file_name"] for f in data["files"])
        assert names == ["a.html", "b.txt"]

    @pytest.mark.unit
    def test_directory_missing_returns_500(self, mock_db, tmp_path):
        """The handler wraps the 404 HTTPException it raises for a missing
        directory in a bare `except Exception`, which re-wraps it as a 500 —
        characterizing that as-is."""
        missing_dir = str(tmp_path / "does-not-exist")
        with patch("app.routes.template.files_list.settings.TEMPLATE_DIR", missing_dir):
            client = _make_client(mock_db)
            resp = client.get("/api/v1/template/files")
        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# GET /files/{filename}
# ---------------------------------------------------------------------------

class TestGetTemplateFile:
    @pytest.mark.unit
    def test_get_file_success(self, mock_db, tmp_path):
        (tmp_path / "a.html").write_text("<b>hi</b>")
        with patch("app.routes.template.files_get.settings.TEMPLATE_DIR", str(tmp_path)), \
             patch("app.routes.template.files_get.settings.ALLOWED_TEMPLATE_TYPES", [".html"]):
            client = _make_client(mock_db)
            resp = client.get("/api/v1/template/files/a.html")
        assert resp.status_code == 200
        assert resp.json()["content"] == "<b>hi</b>"

    @pytest.mark.unit
    def test_get_file_not_found_returns_404(self, mock_db, tmp_path):
        with patch("app.routes.template.files_get.settings.TEMPLATE_DIR", str(tmp_path)), \
             patch("app.routes.template.files_get.settings.ALLOWED_TEMPLATE_TYPES", [".html"]):
            client = _make_client(mock_db)
            resp = client.get("/api/v1/template/files/missing.html")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /content/{template_id}
# ---------------------------------------------------------------------------

class TestGetTemplateContentById:
    @pytest.mark.unit
    def test_content_success(self, mock_db, tmp_path):
        (tmp_path / "reset.html").write_text("content-here")
        template = _make_template(file_path=str(tmp_path / "reset.html"))
        mock_db.execute = AsyncMock(return_value=_scalar(template))
        with patch("app.routes.template.files_get.settings.TEMPLATE_DIR", str(tmp_path)):
            client = _make_client(mock_db)
            resp = client.get(f"/api/v1/template/content/{template.template_id}")
        assert resp.status_code == 200
        assert resp.json()["content"] == "content-here"

    @pytest.mark.unit
    def test_content_template_not_found_returns_404(self, mock_db, tmp_path):
        mock_db.execute = AsyncMock(return_value=_scalar(None))
        with patch("app.routes.template.files_get.settings.TEMPLATE_DIR", str(tmp_path)):
            client = _make_client(mock_db)
            resp = client.get("/api/v1/template/content/NOPE")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /files/{filename}/download
# ---------------------------------------------------------------------------

class TestDownloadTemplateFile:
    @pytest.mark.unit
    def test_download_success(self, mock_db, tmp_path):
        (tmp_path / "a.html").write_text("<b>hi</b>")
        with patch("app.routes.template.files_download.settings.TEMPLATE_DIR", str(tmp_path)):
            client = _make_client(mock_db)
            resp = client.get("/api/v1/template/files/a.html/download")
        assert resp.status_code == 200
        assert resp.content == b"<b>hi</b>"

    @pytest.mark.unit
    def test_download_not_found_returns_404(self, mock_db, tmp_path):
        with patch("app.routes.template.files_download.settings.TEMPLATE_DIR", str(tmp_path)):
            client = _make_client(mock_db)
            resp = client.get("/api/v1/template/files/missing.html/download")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /files/upload
# ---------------------------------------------------------------------------

class TestUploadTemplateFile:
    @pytest.mark.unit
    def test_upload_success(self, mock_db, tmp_path):
        mock_db.refresh = AsyncMock(side_effect=_fake_refresh)
        with patch("app.routes.template.files_upload.settings.TEMPLATE_DIR", str(tmp_path)), \
             patch("app.routes.template.files_upload.settings.ALLOWED_TEMPLATE_TYPES", [".html"]):
            client = _make_client(mock_db)
            resp = client.post(
                "/api/v1/template/files/upload",
                data={
                    "template_type": "PWD",
                    "platform": "BASE",
                    "template_name": "Reset Password",
                },
                files={"file": ("reset.html", b"<html></html>", "text/html")},
            )
        assert resp.status_code == 200
        assert resp.json()["template_name"] == "Reset Password"
        assert (tmp_path / "reset.html").exists()

    @pytest.mark.unit
    def test_upload_invalid_template_type_returns_400(self, mock_db, tmp_path):
        with patch("app.routes.template.files_upload.settings.TEMPLATE_DIR", str(tmp_path)), \
             patch("app.routes.template.files_upload.settings.ALLOWED_TEMPLATE_TYPES", [".html"]):
            client = _make_client(mock_db)
            resp = client.post(
                "/api/v1/template/files/upload",
                data={
                    "template_type": "BOGUS",
                    "platform": "BASE",
                    "template_name": "X",
                },
                files={"file": ("reset.html", b"<html></html>", "text/html")},
            )
        assert resp.status_code == 400

    @pytest.mark.unit
    def test_upload_existing_file_without_overwrite_returns_409(self, mock_db, tmp_path):
        (tmp_path / "reset.html").write_text("old content")
        with patch("app.routes.template.files_upload.settings.TEMPLATE_DIR", str(tmp_path)), \
             patch("app.routes.template.files_upload.settings.ALLOWED_TEMPLATE_TYPES", [".html"]):
            client = _make_client(mock_db)
            resp = client.post(
                "/api/v1/template/files/upload",
                data={
                    "template_type": "PWD",
                    "platform": "BASE",
                    "template_name": "Reset Password",
                },
                files={"file": ("reset.html", b"<html></html>", "text/html")},
            )
        assert resp.status_code == 409


# ---------------------------------------------------------------------------
# PUT /files/{identifier}
# ---------------------------------------------------------------------------

class TestUpdateTemplateFile:
    @pytest.mark.unit
    def test_update_success(self, mock_db, tmp_path):
        (tmp_path / "reset.html").write_text("old content")
        template = _make_template(file_path=str(tmp_path / "reset.html"))
        mock_db.execute = AsyncMock(return_value=_scalar(template))
        with patch("app.routes.template.files_mutate.settings.TEMPLATE_DIR", str(tmp_path)), \
             patch("app.routes.template.files_mutate.settings.ALLOWED_TEMPLATE_TYPES", [".html"]):
            client = _make_client(mock_db)
            resp = client.put(
                f"/api/v1/template/files/{template.template_id}",
                data={"template_name": "Reset Password v2"},
                files={"file": ("reset.html", b"<html>new</html>", "text/html")},
            )
        assert resp.status_code == 200
        assert (tmp_path / "reset.html").read_text() == "<html>new</html>"

    @pytest.mark.unit
    def test_update_record_not_found_returns_404(self, mock_db, tmp_path):
        mock_db.execute = AsyncMock(return_value=_scalar(None))
        with patch("app.routes.template.files_mutate.settings.TEMPLATE_DIR", str(tmp_path)), \
             patch("app.routes.template.files_mutate.settings.ALLOWED_TEMPLATE_TYPES", [".html"]):
            client = _make_client(mock_db)
            resp = client.put(
                "/api/v1/template/files/NOPE",
                data={},
                files={"file": ("reset.html", b"<html>new</html>", "text/html")},
            )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /files/{identifier}
# ---------------------------------------------------------------------------

class TestDeleteTemplateFile:
    @pytest.mark.unit
    def test_delete_success(self, mock_db, tmp_path):
        (tmp_path / "reset.html").write_text("content")
        template = _make_template(file_path=str(tmp_path / "reset.html"))
        mock_db.execute = AsyncMock(return_value=_scalar(template))
        mock_db.delete = AsyncMock()
        with patch("app.routes.template.files_mutate.settings.TEMPLATE_DIR", str(tmp_path)):
            client = _make_client(mock_db)
            resp = client.delete(f"/api/v1/template/files/{template.template_id}")
        assert resp.status_code == 200
        assert not (tmp_path / "reset.html").exists()

    @pytest.mark.unit
    def test_delete_record_not_found_returns_404(self, mock_db, tmp_path):
        mock_db.execute = AsyncMock(return_value=_scalar(None))
        with patch("app.routes.template.files_mutate.settings.TEMPLATE_DIR", str(tmp_path)):
            client = _make_client(mock_db)
            resp = client.delete("/api/v1/template/files/NOPE")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /  (list_templates)
# ---------------------------------------------------------------------------

class TestListTemplates:
    @pytest.mark.unit
    def test_list_success(self, mock_db):
        template = _make_template()
        mock_db.execute = AsyncMock(side_effect=[
            _FakeResult(scalar_val=1),
            _FakeResult(all_=[template]),
        ])
        client = _make_client(mock_db)
        resp = client.get("/api/v1/template/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["templates"][0]["template_id"] == template.template_id

    @pytest.mark.unit
    def test_list_db_error_returns_500(self, mock_db):
        mock_db.execute = AsyncMock(side_effect=Exception("db down"))
        client = _make_client(mock_db)
        resp = client.get("/api/v1/template/")
        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# GET /{identifier}  (get_template)
# ---------------------------------------------------------------------------

class TestGetTemplate:
    @pytest.mark.unit
    def test_get_success(self, mock_db):
        template = _make_template()
        mock_db.execute = AsyncMock(return_value=_scalar(template))
        client = _make_client(mock_db)
        resp = client.get(f"/api/v1/template/{template.template_id}")
        assert resp.status_code == 200
        assert resp.json()["template_id"] == template.template_id

    @pytest.mark.unit
    def test_get_not_found_returns_404(self, mock_db):
        mock_db.execute = AsyncMock(return_value=_scalar(None))
        client = _make_client(mock_db)
        resp = client.get("/api/v1/template/NOPE")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Module-level helper functions (no DB / HTTP involved)
# ---------------------------------------------------------------------------

class TestTemplateIdHelpers:
    @pytest.mark.unit
    def test_generate_template_id_format(self):
        from app.routes.template import generate_template_id
        tid = generate_template_id("PWD", "ZAPT")
        assert tid.startswith("TMPLT_PWD_ZAPT_")

    @pytest.mark.unit
    def test_generate_template_id_invalid_type_raises(self):
        from app.routes.template import generate_template_id
        with pytest.raises(ValueError):
            generate_template_id("BOGUS")

    @pytest.mark.unit
    def test_get_template_type_from_id(self):
        from app.routes.template import get_template_type_from_id
        assert get_template_type_from_id("TMPLT_INVT_BASE_ABCD1234") == "INVT"

    @pytest.mark.unit
    def test_get_platform_from_template_id_defaults_base(self):
        from app.routes.template import get_platform_from_template_id
        assert get_platform_from_template_id("TMPLT_OTH_UNKNOWN_ABCD") == "BASE"

    @pytest.mark.unit
    def test_is_valid_template_id_format(self):
        from app.routes.template import is_valid_template_id_format
        assert is_valid_template_id_format("TMPLT_PWD_BASE_ABCD1234") is True
        assert is_valid_template_id_format("garbage") is False
