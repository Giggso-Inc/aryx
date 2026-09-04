"""
Golden-master / characterization tests for app/routes/apps.py.

Purpose: apps.py is 453 lines with 7 endpoints and had ZERO test coverage
before this file. It is about to be split into a package (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2). Before the
split, we capture the CURRENT observable behavior of every endpoint so the
split can be verified to change nothing.

These are characterization tests, not "correctness" tests: assertions match
what the code actually does today, bugs included. Notably, every endpoint in
this file calls `get_current_user_required(request)` with a single argument
(no `db`), unlike subscriptions.py/gg_channels.py which pass `(request, db)` —
preserved here exactly since we're mocking that dependency directly.

Pattern follows tests/test_channels_characterization.py:
- FastAPI TestClient with `app.include_router(router, prefix=...)`.
- `app.dependency_overrides[get_db] = lambda: mock_db`.
- MagicMock/AsyncMock for services; no real DB, no real HTTP.

Do not modify app/routes/apps.py (or the split package) from this file's
tests beyond what the split itself requires (patch targets).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _make_client(mock_db):
    from app.core.database import get_db
    from app.routes.apps import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/apps")
    app.dependency_overrides[get_db] = lambda: mock_db
    return TestClient(app, raise_server_exceptions=False)


def _auth(user, module):
    """Patch get_current_user_required on the specific submodule that owns
    the endpoint under test. Each submodule in app/routes/apps/ imports
    get_current_user_required itself, so patching the package
    (app.routes.apps.get_current_user_required) would NOT affect the
    submodule's own bound reference — this is the split's "CRITICAL GOTCHA"
    from the compliance plan: patch the exact module path, not the
    re-exporting package.
    """
    return patch(f"app.routes.apps.{module}.get_current_user_required", new=AsyncMock(return_value=user))


class _FakeResult:
    """Mimics the subset of SQLAlchemy's async Result API these endpoints
    call: .scalar_one_or_none(), .scalars().all(), .scalar(), .fetchall()."""

    def __init__(self, scalar_one_or_none=None, all_=None, scalar_val=None, fetchall_=None):
        self._son = scalar_one_or_none
        self._all = all_ if all_ is not None else []
        self._scalar_val = scalar_val
        self._fetchall = fetchall_ if fetchall_ is not None else []

    def scalar_one_or_none(self):
        return self._son

    def scalars(self):
        m = MagicMock()
        m.all = MagicMock(return_value=self._all)
        return m

    def scalar(self):
        return self._scalar_val

    def fetchall(self):
        return self._fetchall


def _exec_seq(*results):
    return AsyncMock(side_effect=list(results))


def _simulate_refresh(obj):
    """Fills in Column defaults that a real DB applies on INSERT/UPDATE
    (created_at, updated_at via func.current_timestamp()). Our mock_db's
    refresh() is a no-op AsyncMock, so without this a freshly-constructed
    App ORM object has these attributes as None, unlike what happens
    against a real database."""
    now = datetime.now(timezone.utc)
    for key in ("created_at", "updated_at"):
        if getattr(obj, key, "unset") is None:
            setattr(obj, key, now)


def _uid():
    return str(uuid.uuid4())


def _mock_app(**overrides):
    now = datetime.now(timezone.utc)
    a = MagicMock()
    a.id = _uid()
    a.app_name = "Slack"
    a.app_key = "slack"
    a.app_description = "Team chat"
    a.app_image = None
    a.is_active = True
    a.is_public = True
    a.version = "1.0"
    a.category = "Communication"
    a.sub_category = None
    a.tags = None
    a.created_at = now
    a.updated_at = now
    for k, v in overrides.items():
        setattr(a, k, v)
    return a


AUTH_HEADERS = {"Authorization": "Bearer test-token"}


@pytest.fixture
def admin_user(admin_user):
    admin_user.is_admin = True
    return admin_user


@pytest.fixture
def regular_user(regular_user):
    regular_user.is_admin = False
    return regular_user


# ===========================================================================
# POST / — create_app
# ===========================================================================

class TestCreateApp:
    def _payload(self, **overrides):
        payload = {"app_name": "Notion", "app_key": "notion"}
        payload.update(overrides)
        return payload

    def test_non_admin_403(self, mock_db, regular_user):
        client = _make_client(mock_db)
        with _auth(regular_user, "create"):
            resp = client.post("/api/v1/apps/", json=self._payload(), headers=AUTH_HEADERS)
        assert resp.status_code == 403
        assert resp.json()["detail"] == "Only administrators can create apps"

    def test_duplicate_name_409(self, mock_db, admin_user):
        existing = _mock_app(app_name="Notion", app_key="other_key")
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=existing))
        client = _make_client(mock_db)
        with _auth(admin_user, "create"):
            resp = client.post("/api/v1/apps/", json=self._payload(), headers=AUTH_HEADERS)
        assert resp.status_code == 409
        assert resp.json()["detail"] == "App with this name already exists"

    def test_success(self, mock_db, admin_user):
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))

        async def _refresh(obj):
            _simulate_refresh(obj)

        mock_db.refresh = AsyncMock(side_effect=_refresh)
        client = _make_client(mock_db)
        with _auth(admin_user, "create"):
            resp = client.post("/api/v1/apps/", json=self._payload(), headers=AUTH_HEADERS)
        assert resp.status_code == 200
        assert resp.json()["app_name"] == "Notion"


# ===========================================================================
# GET / — list_apps
# ===========================================================================

class TestListApps:
    def test_success_empty(self, mock_db, admin_user):
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_val=0),
            _FakeResult(all_=[]),
        )
        client = _make_client(mock_db)
        with _auth(admin_user, "list_apps"):
            resp = client.get("/api/v1/apps/", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["apps"] == []
        assert body["total"] == 0
        assert body["pages"] == 0

    def test_success_with_results(self, mock_db, admin_user):
        app_obj = _mock_app()
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_val=1),
            _FakeResult(all_=[app_obj]),
        )
        client = _make_client(mock_db)
        with _auth(admin_user, "list_apps"):
            resp = client.get("/api/v1/apps/", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        assert len(resp.json()["apps"]) == 1


# ===========================================================================
# GET /categories — get_app_categories
# ===========================================================================

class TestGetAppCategories:
    def test_success(self, mock_db, admin_user):
        mock_db.execute = _exec_seq(_FakeResult(fetchall_=[("Communication",), ("Analytics",), (None,)]))
        client = _make_client(mock_db)
        with _auth(admin_user, "categories_stats"):
            resp = client.get("/api/v1/apps/categories", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["categories"] == ["Analytics", "Communication"]
        assert body["total"] == 2


# ===========================================================================
# GET /stats — get_app_stats
# ===========================================================================

class TestGetAppStats:
    def test_success(self, mock_db, admin_user):
        app_obj = _mock_app()
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_val=10),   # total apps
            _FakeResult(scalar_val=8),    # active apps
            _FakeResult(scalar_val=6),    # public apps
            _FakeResult(fetchall_=[("Communication",)]),  # categories
            _FakeResult(all_=[app_obj]),  # recent apps
        )
        client = _make_client(mock_db)
        with _auth(admin_user, "categories_stats"):
            resp = client.get("/api/v1/apps/stats", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_apps"] == 10
        assert body["active_apps"] == 8
        assert body["public_apps"] == 6
        assert len(body["recent_apps"]) == 1


# ===========================================================================
# GET /{app_id} — get_app
# ===========================================================================

class TestGetApp:
    def test_not_found_404(self, mock_db, admin_user):
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        client = _make_client(mock_db)
        with _auth(admin_user, "detail"):
            resp = client.get(f"/api/v1/apps/{_uid()}", headers=AUTH_HEADERS)
        assert resp.status_code == 404

    def test_private_app_denied_for_non_admin_403(self, mock_db, regular_user):
        app_obj = _mock_app(is_public=False)
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=app_obj))
        client = _make_client(mock_db)
        with _auth(regular_user, "detail"):
            resp = client.get(f"/api/v1/apps/{app_obj.id}", headers=AUTH_HEADERS)
        assert resp.status_code == 403

    def test_success(self, mock_db, admin_user):
        app_obj = _mock_app()
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=app_obj))
        client = _make_client(mock_db)
        with _auth(admin_user, "detail"):
            resp = client.get(f"/api/v1/apps/{app_obj.id}", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        assert resp.json()["app_key"] == "slack"


# ===========================================================================
# PUT /{app_id} — update_app
# ===========================================================================

class TestUpdateApp:
    def test_non_admin_403(self, mock_db, regular_user):
        client = _make_client(mock_db)
        with _auth(regular_user, "detail"):
            resp = client.put(f"/api/v1/apps/{_uid()}", json={"app_name": "New"}, headers=AUTH_HEADERS)
        assert resp.status_code == 403

    def test_not_found_404(self, mock_db, admin_user):
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        client = _make_client(mock_db)
        with _auth(admin_user, "detail"):
            resp = client.put(f"/api/v1/apps/{_uid()}", json={"app_name": "New"}, headers=AUTH_HEADERS)
        assert resp.status_code == 404

    def test_success(self, mock_db, admin_user):
        app_obj = _mock_app()

        async def _refresh(obj):
            _simulate_refresh(obj)

        mock_db.refresh = AsyncMock(side_effect=_refresh)
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=app_obj),  # app lookup
            _FakeResult(scalar_one_or_none=None),       # app_name conflict check (no match)
        )
        client = _make_client(mock_db)
        with _auth(admin_user, "detail"):
            resp = client.put(f"/api/v1/apps/{app_obj.id}", json={"app_name": "Renamed"}, headers=AUTH_HEADERS)
        assert resp.status_code == 200
        assert resp.json()["app_name"] == "Renamed"


# ===========================================================================
# DELETE /{app_id} — delete_app
# ===========================================================================

class TestDeleteApp:
    def test_non_admin_403(self, mock_db, regular_user):
        client = _make_client(mock_db)
        with _auth(regular_user, "detail"):
            resp = client.delete(f"/api/v1/apps/{_uid()}", headers=AUTH_HEADERS)
        assert resp.status_code == 403

    def test_not_found_404(self, mock_db, admin_user):
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        client = _make_client(mock_db)
        with _auth(admin_user, "detail"):
            resp = client.delete(f"/api/v1/apps/{_uid()}", headers=AUTH_HEADERS)
        assert resp.status_code == 404

    def test_success(self, mock_db, admin_user):
        app_obj = _mock_app()
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=app_obj))
        mock_db.delete = AsyncMock()
        client = _make_client(mock_db)
        with _auth(admin_user, "detail"):
            resp = client.delete(f"/api/v1/apps/{app_obj.id}", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        assert resp.json()["message"] == "App deleted successfully"
