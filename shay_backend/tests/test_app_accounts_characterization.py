"""
Golden-master / characterization tests for app/routes/app_accounts.py.

Purpose: app_accounts.py is 755 lines with 7 endpoints and had ZERO test
coverage before this file (grep of tests/ for "app_accounts" /
"app-accounts" turned up nothing). It is about to be split into a package
(see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2).
Before the split, we capture the CURRENT observable behavior of every
endpoint so the split can be verified to change nothing.

These are characterization tests, not "correctness" tests: assertions match
what the code actually does today.

Pattern follows tests/test_channels_characterization.py:
- FastAPI TestClient with `app.include_router(router, prefix=...)`.
- `app.dependency_overrides[get_db] = lambda: mock_db`.
- MagicMock/AsyncMock for services; no real DB, no real HTTP.

Do not modify app/routes/app_accounts.py from this file's tests.
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
    from app.routes.app_accounts import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/app-accounts")
    app.dependency_overrides[get_db] = lambda: mock_db
    return TestClient(app, raise_server_exceptions=False)


AUTH_HEADERS = {"Authorization": "Bearer test-token"}


def _auth(user, module):
    """Patch get_current_user_required on the specific submodule that owns
    the endpoint under test (each submodule imports it directly) -- see the
    CRITICAL GOTCHA in the compliance plan: patching
    app.routes.app_accounts.get_current_user_required would NOT affect a
    submodule's own bound reference."""
    return patch(f"app.routes.app_accounts.{module}.get_current_user_required", new=AsyncMock(return_value=user))


def _uid():
    return str(uuid.uuid4())


class _FakeResult:
    def __init__(self, scalar_one_or_none=None, all_=None, scalar_val=None, first_=None, rows=None):
        self._son = scalar_one_or_none
        self._all = all_ if all_ is not None else []
        self._scalar_val = scalar_val
        self._first = first_
        self._rows = rows if rows is not None else []

    def scalar_one_or_none(self):
        return self._son

    def scalars(self):
        m = MagicMock()
        m.all = MagicMock(return_value=self._all)
        return m

    def scalar(self):
        return self._scalar_val

    def first(self):
        return self._first

    def fetchall(self):
        return self._rows if self._rows else [(x,) for x in self._all]

    def all(self):
        return self._rows if self._rows else self._all


def _exec_seq(*results):
    return AsyncMock(side_effect=list(results))


def _simulate_refresh(obj):
    """Fills in Column defaults that a real DB applies on INSERT (created_at,
    updated_at). mock_db.refresh() is a no-op AsyncMock by default, so
    without this a freshly-constructed AppAccount ORM object has these
    attributes as None, unlike what happens against a real database."""
    now = datetime.utcnow()
    for key in ("created_at", "updated_at"):
        if getattr(obj, key, "unset") is None:
            setattr(obj, key, now)


def _mock_app(**overrides):
    a = MagicMock()
    a.id = _uid()
    a.app_key = "slack"
    a.is_active = True
    for k, v in overrides.items():
        setattr(a, k, v)
    return a


def _mock_channel(**overrides):
    ch = MagicMock()
    ch.id = _uid()
    ch.company_id = "company-001"
    ch.is_accessible_by_user = MagicMock(return_value=True)
    for k, v in overrides.items():
        setattr(ch, k, v)
    return ch


def _mock_app_account(**overrides):
    acc = MagicMock()
    acc.id = _uid()
    acc.app_id = _uid()
    acc.channel_id = _uid()
    acc.connection_name = "conn"
    acc.connection_status = "active"
    acc.connection_settings = None
    acc.webhook_url = None
    acc.callback_url = None
    acc.is_active = True
    acc.auto_sync = False
    acc.sync_interval = 3600
    acc.connected_by = "user-admin-001"
    acc.last_sync_at = None
    acc.sync_status = None
    acc.error_message = None
    acc.created_at = datetime.utcnow()
    acc.updated_at = datetime.utcnow()
    for k, v in overrides.items():
        setattr(acc, k, v)
    return acc


def _mock_user_row(**overrides):
    u = MagicMock()
    u.id = "user-admin-001"
    u.email_id = "admin@example.com"
    u.name = "Admin User"
    u.avatar_url = None
    for k, v in overrides.items():
        setattr(u, k, v)
    return u


# ===========================================================================
# POST / — create_app_account
# ===========================================================================

class TestCreateAppAccount:
    def _payload(self, **overrides):
        payload = {"app_id": _uid(), "channel_id": _uid(), "connection_status": "active"}
        payload.update(overrides)
        return payload

    def test_app_not_found_404(self, mock_db, admin_user):
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        client = _make_client(mock_db)
        with _auth(admin_user, "create"):
            resp = client.post("/api/v1/app-accounts/", json=self._payload(), headers=AUTH_HEADERS)
        assert resp.status_code == 404
        assert "App not found" in resp.json()["detail"]

    def test_channel_not_found_404(self, mock_db, admin_user):
        app_obj = _mock_app()
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=app_obj),
            _FakeResult(scalar_one_or_none=None),
        )
        client = _make_client(mock_db)
        with _auth(admin_user, "create"):
            resp = client.post("/api/v1/app-accounts/", json=self._payload(), headers=AUTH_HEADERS)
        assert resp.status_code == 404
        assert "Channel not found" in resp.json()["detail"]

    def test_channel_access_denied_403(self, mock_db, admin_user):
        app_obj = _mock_app()
        channel = _mock_channel()
        channel.is_accessible_by_user = MagicMock(return_value=False)
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=app_obj),
            _FakeResult(scalar_one_or_none=channel),
        )
        client = _make_client(mock_db)
        with _auth(admin_user, "create"):
            resp = client.post("/api/v1/app-accounts/", json=self._payload(), headers=AUTH_HEADERS)
        assert resp.status_code == 403

    def test_duplicate_connection_409(self, mock_db, admin_user):
        app_obj = _mock_app()
        channel = _mock_channel()
        existing = _mock_app_account()
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=app_obj),
            _FakeResult(scalar_one_or_none=channel),
            _FakeResult(scalar_one_or_none=existing),
        )
        client = _make_client(mock_db)
        with _auth(admin_user, "create"):
            resp = client.post("/api/v1/app-accounts/", json=self._payload(), headers=AUTH_HEADERS)
        assert resp.status_code == 409

    def test_happy_path_non_sharepoint(self, mock_db, admin_user):
        app_obj = _mock_app(app_key="slack")
        channel = _mock_channel()
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=app_obj),
            _FakeResult(scalar_one_or_none=channel),
            _FakeResult(scalar_one_or_none=None),
        )
        mock_db.refresh = AsyncMock(side_effect=_simulate_refresh)
        client = _make_client(mock_db)
        with _auth(admin_user, "create"):
            resp = client.post("/api/v1/app-accounts/", json=self._payload(), headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["connection_status"] == "active"
        assert body["user_metadata"]["user_id"] == str(admin_user.id)

    def test_jira_provider_injects_client_credentials(self, mock_db, admin_user):
        app_obj = _mock_app(app_key="jira")
        channel = _mock_channel()
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=app_obj),
            _FakeResult(scalar_one_or_none=channel),
            _FakeResult(scalar_one_or_none=None),
        )
        mock_db.refresh = AsyncMock(side_effect=_simulate_refresh)
        client = _make_client(mock_db)
        with _auth(admin_user, "create"):
            resp = client.post(
                "/api/v1/app-accounts/",
                json=self._payload(connection_settings={"provider": "jira"}),
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 200
        assert resp.json()["connection_settings"]["client_id"]

    def test_sharepoint_vault_failure_500(self, mock_db, admin_user):
        """Characterization: when app_key is sharepoint and vault save fails,
        handle_app_account_vault_integration raises HTTPException(500), which
        create_app_account re-raises as-is (`except HTTPException as e: raise
        e`). Documented as-is."""
        app_obj = _mock_app(app_key="sharepoint")
        channel = _mock_channel()
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=app_obj),
            _FakeResult(scalar_one_or_none=channel),
            _FakeResult(scalar_one_or_none=None),
        )
        client = _make_client(mock_db)
        with _auth(admin_user, "create"), \
                patch("app.routes.app_accounts.create.handle_app_account_vault_integration", new=AsyncMock(
                    side_effect=Exception("Failed to save credentials to vault"))):
            resp = client.post(
                "/api/v1/app-accounts/",
                json=self._payload(connection_settings={"provider": "sharepoint", "client_id": "abc"}),
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 500
        assert "Failed to integrate with vault service" in resp.json()["detail"]


# ===========================================================================
# GET / — list_app_accounts
# ===========================================================================

class TestListAppAccounts:
    def test_happy_path_empty(self, mock_db, admin_user):
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_val=0),
            _FakeResult(rows=[]),
        )
        client = _make_client(mock_db)
        with _auth(admin_user, "list_"):
            resp = client.get("/api/v1/app-accounts/", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["app_accounts"] == []
        assert body["total"] == 0
        assert body["pages"] == 0

    def test_happy_path_with_one_result(self, mock_db, admin_user):
        acc = _mock_app_account()
        user_row = _mock_user_row()
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_val=1),
            _FakeResult(rows=[(acc, user_row)]),
        )
        client = _make_client(mock_db)
        with _auth(admin_user, "list_"):
            resp = client.get("/api/v1/app-accounts/", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["app_accounts"][0]["id"] == str(acc.id)


# ===========================================================================
# GET /stats — get_app_account_stats
# ===========================================================================

class TestGetAppAccountStats:
    def test_happy_path_no_recent_connections(self, mock_db, admin_user):
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_val=0),   # total
            _FakeResult(scalar_val=0),   # active
            _FakeResult(scalar_val=0),   # error
            _FakeResult(rows=[]),        # apps_connected
            _FakeResult(rows=[]),        # channels_connected
            _FakeResult(all_=[]),        # recent_connections
            _FakeResult(all_=[]),        # users_by_id
        )
        client = _make_client(mock_db)
        with _auth(admin_user, "stats"):
            resp = client.get("/api/v1/app-accounts/stats", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_connections"] == 0
        assert body["recent_connections"] == []


# ===========================================================================
# GET /{app_account_id} — get_app_account
# ===========================================================================

class TestGetAppAccount:
    def test_not_found_404(self, mock_db, admin_user):
        mock_db.execute = _exec_seq(_FakeResult(first_=None))
        client = _make_client(mock_db)
        with _auth(admin_user, "detail"):
            resp = client.get(f"/api/v1/app-accounts/{_uid()}", headers=AUTH_HEADERS)
        assert resp.status_code == 404

    def test_cross_company_403(self, mock_db, admin_user):
        acc = _mock_app_account()
        mock_db.execute = _exec_seq(_FakeResult(first_=(acc, "other-company")))
        client = _make_client(mock_db)
        with _auth(admin_user, "detail"):
            resp = client.get(f"/api/v1/app-accounts/{acc.id}", headers=AUTH_HEADERS)
        assert resp.status_code == 403

    def test_happy_path(self, mock_db, admin_user):
        acc = _mock_app_account()
        user_row = _mock_user_row()
        mock_db.execute = _exec_seq(
            _FakeResult(first_=(acc, admin_user.company_id)),
            _FakeResult(scalar_one_or_none=user_row),
        )
        client = _make_client(mock_db)
        with _auth(admin_user, "detail"):
            resp = client.get(f"/api/v1/app-accounts/{acc.id}", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        assert resp.json()["id"] == str(acc.id)


# ===========================================================================
# PUT /{app_account_id} — update_app_account
# ===========================================================================

class TestUpdateAppAccount:
    def test_not_found_404(self, mock_db, admin_user):
        mock_db.execute = _exec_seq(_FakeResult(first_=None))
        client = _make_client(mock_db)
        with _auth(admin_user, "mutate"):
            resp = client.put(
                f"/api/v1/app-accounts/{_uid()}",
                json={"connection_name": "new-name"},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 404

    def test_happy_path_simple_field_update(self, mock_db, admin_user):
        acc = _mock_app_account(connection_name="old")
        app_obj = _mock_app(app_key="slack")
        user_row = _mock_user_row()
        mock_db.execute = _exec_seq(
            _FakeResult(first_=(acc, admin_user.company_id)),
            _FakeResult(scalar_one_or_none=app_obj),
            _FakeResult(scalar_one_or_none=user_row),
        )
        client = _make_client(mock_db)
        with _auth(admin_user, "mutate"):
            resp = client.put(
                f"/api/v1/app-accounts/{acc.id}",
                json={"connection_name": "new-name"},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 200
        assert acc.connection_name == "new-name"


# ===========================================================================
# DELETE /{app_account_id} — delete_app_account
# ===========================================================================

class TestDeleteAppAccount:
    def test_not_found_404(self, mock_db, admin_user):
        mock_db.execute = _exec_seq(_FakeResult(first_=None))
        client = _make_client(mock_db)
        with _auth(admin_user, "detail"):
            resp = client.delete(f"/api/v1/app-accounts/{_uid()}", headers=AUTH_HEADERS)
        assert resp.status_code == 404

    def test_happy_path(self, mock_db, admin_user):
        acc = _mock_app_account()
        mock_db.execute = _exec_seq(_FakeResult(first_=(acc, admin_user.company_id)))
        client = _make_client(mock_db)
        with _auth(admin_user, "detail"):
            resp = client.delete(f"/api/v1/app-accounts/{acc.id}", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        assert resp.json() == {"message": "App account deleted successfully"}
        mock_db.delete.assert_awaited_with(acc)


# ===========================================================================
# POST /connect — connect_app_to_channel
# ===========================================================================

class TestConnectAppToChannel:
    def _payload(self, **overrides):
        payload = {"app_id": _uid(), "channel_id": _uid()}
        payload.update(overrides)
        return payload

    def test_app_not_found_404(self, mock_db, admin_user):
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        client = _make_client(mock_db)
        with _auth(admin_user, "connect"):
            resp = client.post("/api/v1/app-accounts/connect", json=self._payload(), headers=AUTH_HEADERS)
        assert resp.status_code == 404

    def test_happy_path(self, mock_db, admin_user):
        app_obj = _mock_app(app_key="slack")
        channel = _mock_channel()
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=app_obj),
            _FakeResult(scalar_one_or_none=channel),
            _FakeResult(scalar_one_or_none=None),
        )
        mock_db.refresh = AsyncMock(side_effect=_simulate_refresh)
        client = _make_client(mock_db)
        with _auth(admin_user, "connect"):
            resp = client.post("/api/v1/app-accounts/connect", json=self._payload(), headers=AUTH_HEADERS)
        assert resp.status_code == 200
        assert resp.json()["connection_status"] == "active"
        assert resp.json()["is_active"] is True
