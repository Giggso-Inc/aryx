"""
Unit tests for /gg-app-connections endpoints.

All tests are pure-unit: no real DB, no real auth.
Each test mocks db.execute via side_effect chains that match the
call sequence in the route handler.
"""

import os
import sys
import uuid
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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import get_db
from app.routes.gg_app_connections import router as conn_router

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_WS_ID   = "550e8400-e29b-41d4-a716-446655440000"
_CH_ID   = "550e8400-e29b-41d4-a716-446655440001"
_TH_ID   = "550e8400-e29b-41d4-a716-446655440002"
_APP_ID  = "550e8400-e29b-41d4-a716-446655440020"
_CONN_ID = "550e8400-e29b-41d4-a716-446655440030"

# ---------------------------------------------------------------------------
# DB result helpers
# ---------------------------------------------------------------------------

def _scalar(value):
    """Build a mock execute result whose .scalar_one_or_none() returns value."""
    r = MagicMock()
    r.scalar_one_or_none = MagicMock(return_value=value)
    r.scalar = MagicMock(return_value=0)
    r.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    r.first = MagicMock(return_value=None)
    return r


def _scalars_result(items):
    """Build a mock execute result whose .scalars().all() returns items."""
    r = MagicMock()
    r.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=items)))
    r.scalar_one_or_none = MagicMock(return_value=None)
    r.scalar = MagicMock(return_value=len(items))
    r.all = MagicMock(return_value=items)
    r.first = MagicMock(return_value=items[0] if items else None)
    return r


def _count_result(n):
    """Build a mock execute result whose .scalar() returns n (for COUNT queries)."""
    r = MagicMock()
    r.scalar = MagicMock(return_value=n)
    r.scalar_one_or_none = MagicMock(return_value=None)
    r.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    return r


# ---------------------------------------------------------------------------
# Domain mock builders
# ---------------------------------------------------------------------------

def _make_conn_mock(level="channel", **kw):
    conn = MagicMock()
    conn.id = uuid.UUID(_CONN_ID)
    conn.app_id = uuid.UUID(_APP_ID)
    conn.level = level
    conn.workspace_id = uuid.UUID(_WS_ID) if level == "workspace" else None
    conn.channel_id   = uuid.UUID(_CH_ID) if level == "channel"   else None
    conn.thread_id    = uuid.UUID(_TH_ID) if level == "thread"    else None
    conn.connected_by = "user-admin-001"
    conn.connection_name = "Test Connection"
    conn.connection_status = "active"
    conn.connection_settings = {}
    conn.webhook_url = None
    conn.callback_url = None
    conn.is_active = True
    conn.auto_sync = False
    conn.sync_interval = 3600
    conn.last_sync_at = None
    conn.sync_status = None
    conn.error_message = None
    conn.provider = None
    conn.provider_account_id = None
    conn.auth_type = "oauth2"
    conn.last_token_refresh = None
    conn.token_expires_at = None
    conn.created_at = None
    conn.updated_at = None
    conn.to_dict = MagicMock(return_value={"id": str(conn.id), "level": level})
    for k, v in kw.items():
        setattr(conn, k, v)
    return conn


def _make_workspace_mock():
    ws = MagicMock()
    ws.id = uuid.UUID(_WS_ID)
    ws.company_id = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    return ws


def _make_channel_mock():
    ch = MagicMock()
    ch.id = uuid.UUID(_CH_ID)
    ch.company_id = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    return ch


def _make_app_mock():
    a = MagicMock()
    a.id = uuid.UUID(_APP_ID)
    a.is_active = True
    return a


def _make_user_mock():
    u = MagicMock()
    u.id = "user-admin-001"
    u.name = "Admin User"
    u.email_id = "admin@example.com"
    u.avatar_url = None
    return u


def _make_member_mock():
    m = MagicMock()
    m.id = "member-001"
    m.user_id = "user-admin-001"
    m.is_active = True
    return m


# ---------------------------------------------------------------------------
# Client factory
# ---------------------------------------------------------------------------

def _make_client(mock_db):
    app = FastAPI()
    app.include_router(conn_router, prefix="/gg-app-connections")
    app.dependency_overrides[get_db] = lambda: mock_db
    return TestClient(app)


# ---------------------------------------------------------------------------
# TestGetResolvedConnection
# ---------------------------------------------------------------------------

class TestGetResolvedConnection:

    @pytest.mark.unit
    def test_resolved_connection_found(self, mock_db):
        """resolve_gg_app_connection returns conn → 200 with to_dict payload."""
        conn = _make_conn_mock(level="channel")
        admin_user = _make_user_mock()

        with patch(
            "app.routes.gg_app_connections.get_current_user_required",
            new=AsyncMock(return_value=admin_user),
        ), patch(
            "app.routes.gg_app_connections.resolve_gg_app_connection",
            new=AsyncMock(return_value=conn),
        ):
            client = _make_client(mock_db)
            resp = client.get(
                "/gg-app-connections/resolved",
                params={"app_key": "slack", "channel_id": _CH_ID},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == _CONN_ID

    @pytest.mark.unit
    def test_resolved_connection_not_found(self, mock_db):
        """resolve_gg_app_connection returns None → 404."""
        admin_user = _make_user_mock()

        with patch(
            "app.routes.gg_app_connections.get_current_user_required",
            new=AsyncMock(return_value=admin_user),
        ), patch(
            "app.routes.gg_app_connections.resolve_gg_app_connection",
            new=AsyncMock(return_value=None),
        ):
            client = _make_client(mock_db)
            resp = client.get(
                "/gg-app-connections/resolved",
                params={"app_key": "slack", "channel_id": _CH_ID},
            )

        assert resp.status_code == 404

    @pytest.mark.unit
    def test_resolved_missing_app_key_returns_422(self, mock_db):
        """Missing required app_key query param → FastAPI returns 422."""
        admin_user = _make_user_mock()

        with patch(
            "app.routes.gg_app_connections.get_current_user_required",
            new=AsyncMock(return_value=admin_user),
        ):
            client = _make_client(mock_db)
            resp = client.get("/gg-app-connections/resolved")

        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# TestCreateConnection
# ---------------------------------------------------------------------------

class TestCreateConnection:

    def _post(self, client, body, admin_user):
        with patch(
            "app.routes.gg_app_connections.get_current_user_required",
            new=AsyncMock(return_value=admin_user),
        ):
            return client.post("/gg-app-connections/", json=body)

    @pytest.mark.unit
    def test_create_channel_connection_success(self, mock_db):
        """Happy path: channel-level connection is created → 201."""
        admin_user = _make_user_mock()
        admin_user.id = "user-admin-001"
        admin_user.company_id = "company-001"

        app_mock     = _make_app_mock()
        channel_mock = _make_channel_mock()
        member_mock  = _make_member_mock()
        conn_mock    = _make_conn_mock(level="channel")

        # Call order:
        # 1. App lookup (create_connection)
        # 2. Channel lookup (_assert_scope_exists)
        # 3. GGMember lookup (_assert_member_access)
        # 4. Duplicate check
        mock_db.execute = AsyncMock(side_effect=[
            _scalar(app_mock),      # app exists
            _scalar(channel_mock),  # channel exists
            _scalar(member_mock),   # member access granted
            _scalar(None),          # no duplicate
        ])
        mock_db.refresh = AsyncMock(side_effect=lambda obj: setattr(obj, "__refreshed__", True))

        client = _make_client(mock_db)
        resp = self._post(client, {
            "app_id": _APP_ID,
            "level": "channel",
            "channel_id": _CH_ID,
            "connection_name": "My Connection",
            "connection_status": "active",
        }, admin_user)
        assert resp.status_code == 201

    @pytest.mark.unit
    def test_create_workspace_connection_success(self, mock_db):
        """Happy path: workspace-level connection is created → 201."""
        admin_user = _make_user_mock()
        admin_user.id = "user-admin-001"
        admin_user.company_id = "company-001"

        app_mock  = _make_app_mock()
        ws_mock   = _make_workspace_mock()
        member_mock = _make_member_mock()
        conn_mock = _make_conn_mock(level="workspace")

        mock_db.execute = AsyncMock(side_effect=[
            _scalar(app_mock),     # app exists
            _scalar(ws_mock),      # workspace exists
            _scalar(member_mock),  # member access
            _scalar(None),         # no duplicate
        ])

        client = _make_client(mock_db)
        resp = self._post(client, {
            "app_id": _APP_ID,
            "level": "workspace",
            "workspace_id": _WS_ID,
            "connection_name": "WS Connection",
            "connection_status": "active",
        }, admin_user)
        assert resp.status_code == 201

    @pytest.mark.unit
    def test_create_thread_connection_success(self, mock_db):
        """Happy path: thread-level connection is created → 201."""
        admin_user = _make_user_mock()
        admin_user.id = "user-admin-001"
        admin_user.company_id = "company-001"

        app_mock    = _make_app_mock()
        member_mock = _make_member_mock()
        conn_mock   = _make_conn_mock(level="thread")

        # Thread scope: _assert_scope_exists returns None (no DB query for thread),
        # _assert_member_access: thread member lookup, then fallback channel member lookup
        mock_db.execute = AsyncMock(side_effect=[
            _scalar(app_mock),     # app exists
            # _assert_scope_exists for "thread" does NOT query the DB (returns None directly)
            _scalar(member_mock),  # thread GGMember lookup
            _scalar(None),         # no duplicate
        ])

        client = _make_client(mock_db)
        resp = self._post(client, {
            "app_id": _APP_ID,
            "level": "thread",
            "thread_id": _TH_ID,
            "connection_name": "Thread Connection",
            "connection_status": "active",
        }, admin_user)
        assert resp.status_code == 201

    @pytest.mark.unit
    def test_create_app_not_found_returns_404(self, mock_db):
        """App not found or inactive → 404."""
        admin_user = _make_user_mock()
        admin_user.company_id = "company-001"

        mock_db.execute = AsyncMock(return_value=_scalar(None))

        with patch(
            "app.routes.gg_app_connections.get_current_user_required",
            new=AsyncMock(return_value=admin_user),
        ):
            client = _make_client(mock_db)
            resp = client.post("/gg-app-connections/", json={
                "app_id": _APP_ID,
                "level": "channel",
                "channel_id": _CH_ID,
                "connection_status": "active",
            })

        assert resp.status_code == 404

    @pytest.mark.unit
    def test_create_duplicate_returns_409(self, mock_db):
        """Duplicate active connection at same scope → 409."""
        admin_user = _make_user_mock()
        admin_user.id = "user-admin-001"
        admin_user.company_id = "company-001"

        app_mock     = _make_app_mock()
        channel_mock = _make_channel_mock()
        member_mock  = _make_member_mock()
        existing     = _make_conn_mock(level="channel")

        mock_db.execute = AsyncMock(side_effect=[
            _scalar(app_mock),      # app exists
            _scalar(channel_mock),  # channel exists
            _scalar(member_mock),   # member access
            _scalar(existing),      # duplicate found
        ])

        with patch(
            "app.routes.gg_app_connections.get_current_user_required",
            new=AsyncMock(return_value=admin_user),
        ):
            client = _make_client(mock_db)
            resp = client.post("/gg-app-connections/", json={
                "app_id": _APP_ID,
                "level": "channel",
                "channel_id": _CH_ID,
                "connection_status": "active",
            })

        assert resp.status_code == 409

    @pytest.mark.unit
    def test_create_invalid_scope_returns_422(self, mock_db):
        """level=channel but workspace_id set (exclusive arc violation) → 422."""
        admin_user = _make_user_mock()
        admin_user.company_id = "company-001"

        with patch(
            "app.routes.gg_app_connections.get_current_user_required",
            new=AsyncMock(return_value=admin_user),
        ):
            client = _make_client(mock_db)
            # Provide both channel_id AND workspace_id → model_validator raises ValueError → 422
            resp = client.post("/gg-app-connections/", json={
                "app_id": _APP_ID,
                "level": "channel",
                "channel_id": _CH_ID,
                "workspace_id": _WS_ID,
                "connection_status": "active",
            })

        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# TestListConnections
# ---------------------------------------------------------------------------

class TestListConnections:

    @pytest.mark.unit
    def test_list_returns_connections(self, mock_db):
        """GET / returns 200 with connections list."""
        admin_user = _make_user_mock()
        admin_user.company_id = "company-001"
        admin_user.id = "user-admin-001"

        conn      = _make_conn_mock(level="channel")
        user_mock = _make_user_mock()

        result_count = _count_result(1)
        result_rows  = _scalars_result([conn])
        result_users = _scalars_result([user_mock])

        mock_db.execute = AsyncMock(side_effect=[result_count, result_rows, result_users])

        with patch(
            "app.routes.gg_app_connections.get_current_user_required",
            new=AsyncMock(return_value=admin_user),
        ):
            client = _make_client(mock_db)
            resp = client.get("/gg-app-connections/")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["connections"]) == 1

    @pytest.mark.unit
    def test_list_empty(self, mock_db):
        """GET / with no connections → 200, empty list."""
        admin_user = _make_user_mock()
        admin_user.company_id = "company-001"
        admin_user.id = "user-admin-001"

        result_count = _count_result(0)
        result_rows  = _scalars_result([])
        # No users fetch when rows is empty

        mock_db.execute = AsyncMock(side_effect=[result_count, result_rows])

        with patch(
            "app.routes.gg_app_connections.get_current_user_required",
            new=AsyncMock(return_value=admin_user),
        ):
            client = _make_client(mock_db)
            resp = client.get("/gg-app-connections/")

        assert resp.status_code == 200
        data = resp.json()
        assert data["connections"] == []
        assert data["total"] == 0

    @pytest.mark.unit
    def test_list_with_level_filter(self, mock_db):
        """GET /?level=channel filters correctly → 200."""
        admin_user = _make_user_mock()
        admin_user.company_id = "company-001"
        admin_user.id = "user-admin-001"

        conn      = _make_conn_mock(level="channel")
        user_mock = _make_user_mock()

        result_count = _count_result(1)
        result_rows  = _scalars_result([conn])
        result_users = _scalars_result([user_mock])

        mock_db.execute = AsyncMock(side_effect=[result_count, result_rows, result_users])

        with patch(
            "app.routes.gg_app_connections.get_current_user_required",
            new=AsyncMock(return_value=admin_user),
        ):
            client = _make_client(mock_db)
            resp = client.get("/gg-app-connections/?level=channel")

        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# TestGetConnection
# ---------------------------------------------------------------------------

class TestGetConnection:

    @pytest.mark.unit
    def test_get_found(self, mock_db):
        """GET /{id} returns 200 with correct connection id."""
        admin_user = _make_user_mock()
        admin_user.id = "user-admin-001"
        admin_user.company_id = "company-001"

        conn         = _make_conn_mock(level="channel")
        channel_mock = _make_channel_mock()
        member_mock  = _make_member_mock()
        user_mock    = _make_user_mock()

        # Call order:
        # 1. conn lookup
        # 2. channel lookup (_assert_scope_exists)
        # 3. member lookup (_assert_member_access)
        # 4. connector user lookup
        mock_db.execute = AsyncMock(side_effect=[
            _scalar(conn),          # connection found
            _scalar(channel_mock),  # scope exists
            _scalar(member_mock),   # member access
            _scalar(user_mock),     # connector user
        ])

        with patch(
            "app.routes.gg_app_connections.get_current_user_required",
            new=AsyncMock(return_value=admin_user),
        ):
            client = _make_client(mock_db)
            resp = client.get(f"/gg-app-connections/{_CONN_ID}")

        assert resp.status_code == 200
        assert resp.json()["id"] == _CONN_ID

    @pytest.mark.unit
    def test_get_not_found_returns_404(self, mock_db):
        """GET /{id} when connection doesn't exist → 404."""
        admin_user = _make_user_mock()
        admin_user.company_id = "company-001"

        mock_db.execute = AsyncMock(return_value=_scalar(None))

        with patch(
            "app.routes.gg_app_connections.get_current_user_required",
            new=AsyncMock(return_value=admin_user),
        ):
            client = _make_client(mock_db)
            resp = client.get(f"/gg-app-connections/{_CONN_ID}")

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# TestUpdateConnection
# ---------------------------------------------------------------------------

class TestUpdateConnection:

    @pytest.mark.unit
    def test_update_success(self, mock_db):
        """PUT /{id} updates fields and returns 200."""
        admin_user = _make_user_mock()
        admin_user.id = "user-admin-001"
        admin_user.company_id = "company-001"

        conn         = _make_conn_mock(level="channel")
        channel_mock = _make_channel_mock()
        member_mock  = _make_member_mock()
        user_mock    = _make_user_mock()

        # Call order:
        # 1. conn lookup
        # 2. channel lookup (_assert_scope_exists)
        # 3. member lookup (_assert_member_access)
        # 4. connector user lookup (after commit/refresh)
        mock_db.execute = AsyncMock(side_effect=[
            _scalar(conn),          # connection found
            _scalar(channel_mock),  # scope exists
            _scalar(member_mock),   # member access
            _scalar(user_mock),     # connector user
        ])

        with patch(
            "app.routes.gg_app_connections.get_current_user_required",
            new=AsyncMock(return_value=admin_user),
        ):
            client = _make_client(mock_db)
            resp = client.put(
                f"/gg-app-connections/{_CONN_ID}",
                json={"connection_name": "Updated"},
            )

        assert resp.status_code == 200

    @pytest.mark.unit
    def test_update_not_found_returns_404(self, mock_db):
        """PUT /{id} when connection doesn't exist → 404."""
        admin_user = _make_user_mock()
        admin_user.company_id = "company-001"

        mock_db.execute = AsyncMock(return_value=_scalar(None))

        with patch(
            "app.routes.gg_app_connections.get_current_user_required",
            new=AsyncMock(return_value=admin_user),
        ):
            client = _make_client(mock_db)
            resp = client.put(
                f"/gg-app-connections/{_CONN_ID}",
                json={"connection_name": "Updated"},
            )

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# TestDeleteConnection
# ---------------------------------------------------------------------------

class TestDeleteConnection:

    @pytest.mark.unit
    def test_delete_success(self, mock_db):
        """DELETE /{id} removes the connection and returns 200 with message."""
        admin_user = _make_user_mock()
        admin_user.id = "user-admin-001"
        admin_user.company_id = "company-001"

        conn         = _make_conn_mock(level="channel")
        channel_mock = _make_channel_mock()
        member_mock  = _make_member_mock()

        # Call order:
        # 1. conn lookup
        # 2. channel lookup (_assert_scope_exists)
        # 3. member lookup (_assert_member_access)
        mock_db.execute = AsyncMock(side_effect=[
            _scalar(conn),          # connection found
            _scalar(channel_mock),  # scope exists
            _scalar(member_mock),   # member access
        ])
        mock_db.delete = AsyncMock()

        with patch(
            "app.routes.gg_app_connections.get_current_user_required",
            new=AsyncMock(return_value=admin_user),
        ):
            client = _make_client(mock_db)
            resp = client.delete(f"/gg-app-connections/{_CONN_ID}")

        assert resp.status_code == 200
        assert "message" in resp.json()

    @pytest.mark.unit
    def test_delete_not_found_returns_404(self, mock_db):
        """DELETE /{id} when connection doesn't exist → 404."""
        admin_user = _make_user_mock()
        admin_user.company_id = "company-001"

        mock_db.execute = AsyncMock(return_value=_scalar(None))

        with patch(
            "app.routes.gg_app_connections.get_current_user_required",
            new=AsyncMock(return_value=admin_user),
        ):
            client = _make_client(mock_db)
            resp = client.delete(f"/gg-app-connections/{_CONN_ID}")

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# TestListConnectionsByScope
# ---------------------------------------------------------------------------

class TestListConnectionsByScope:

    def _get_scope(self, client, scope_type, scope_id, admin_user, **params):
        with patch(
            "app.routes.gg_app_connections.get_current_user_required",
            new=AsyncMock(return_value=admin_user),
        ):
            return client.get(
                f"/gg-app-connections/scope/{scope_type}/{scope_id}",
                params=params,
            )

    @pytest.mark.unit
    def test_list_by_workspace_scope(self, mock_db):
        """GET /scope/workspace/{id} → 200 with connection list."""
        admin_user = _make_user_mock()
        admin_user.id = "user-admin-001"
        admin_user.company_id = "company-001"

        ws_mock     = _make_workspace_mock()
        member_mock = _make_member_mock()
        conn        = _make_conn_mock(level="workspace")
        user_mock   = _make_user_mock()

        # Call order:
        # 1. workspace lookup (_assert_scope_exists)
        # 2. member lookup (_assert_member_access)
        # 3. count query
        # 4. rows query
        # 5. users batch query
        result_count = _count_result(1)
        result_rows  = _scalars_result([conn])
        result_users = _scalars_result([user_mock])

        mock_db.execute = AsyncMock(side_effect=[
            _scalar(ws_mock),    # scope exists
            _scalar(member_mock), # member access
            result_count,
            result_rows,
            result_users,
        ])

        client = _make_client(mock_db)
        resp = self._get_scope(client, "workspace", _WS_ID, admin_user)

        assert resp.status_code == 200
        data = resp.json()
        assert "connections" in data

    @pytest.mark.unit
    def test_list_by_channel_scope(self, mock_db):
        """GET /scope/channel/{id} → 200 with connection list."""
        admin_user = _make_user_mock()
        admin_user.id = "user-admin-001"
        admin_user.company_id = "company-001"

        ch_mock     = _make_channel_mock()
        member_mock = _make_member_mock()
        conn        = _make_conn_mock(level="channel")
        user_mock   = _make_user_mock()

        result_count = _count_result(1)
        result_rows  = _scalars_result([conn])
        result_users = _scalars_result([user_mock])

        mock_db.execute = AsyncMock(side_effect=[
            _scalar(ch_mock),     # scope exists
            _scalar(member_mock), # member access
            result_count,
            result_rows,
            result_users,
        ])

        client = _make_client(mock_db)
        resp = self._get_scope(client, "channel", _CH_ID, admin_user)

        assert resp.status_code == 200

    @pytest.mark.unit
    def test_list_by_thread_scope(self, mock_db):
        """GET /scope/thread/{id} → 200; thread member check uses GGMember lookup."""
        admin_user = _make_user_mock()
        admin_user.id = "user-admin-001"
        admin_user.company_id = "company-001"

        member_mock = _make_member_mock()
        conn        = _make_conn_mock(level="thread")
        user_mock   = _make_user_mock()

        # Thread scope: _assert_scope_exists returns None without DB query.
        # _assert_member_access: thread GGMember lookup (found → returns immediately).
        result_count = _count_result(1)
        result_rows  = _scalars_result([conn])
        result_users = _scalars_result([user_mock])

        mock_db.execute = AsyncMock(side_effect=[
            # _assert_scope_exists for "thread" → no DB call
            _scalar(member_mock), # thread member lookup
            result_count,
            result_rows,
            result_users,
        ])

        client = _make_client(mock_db)
        resp = self._get_scope(client, "thread", _TH_ID, admin_user)

        assert resp.status_code == 200

    @pytest.mark.unit
    def test_invalid_scope_type_returns_400(self, mock_db):
        """scope_type not in (workspace, channel, thread) → 400."""
        admin_user = _make_user_mock()
        admin_user.company_id = "company-001"

        client = _make_client(mock_db)
        resp = self._get_scope(client, "invalid", _WS_ID, admin_user)

        assert resp.status_code == 400

    @pytest.mark.unit
    def test_invalid_scope_uuid_returns_400(self, mock_db):
        """scope_id that is not a valid UUID → 400."""
        admin_user = _make_user_mock()
        admin_user.company_id = "company-001"

        client = _make_client(mock_db)
        resp = self._get_scope(client, "workspace", "not-a-uuid", admin_user)

        assert resp.status_code == 400
