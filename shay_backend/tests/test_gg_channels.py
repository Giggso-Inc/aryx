"""
Unit tests for /gg-channels endpoints.

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

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CH_ID     = "550e8400-e29b-41d4-a716-446655440001"
_USER_ID   = "550e8400-e29b-41d4-a716-446655440005"
_MEMBER_ID = "550e8400-e29b-41d4-a716-446655440010"
_APP_ID    = "550e8400-e29b-41d4-a716-446655440020"
_CONN_ID   = "550e8400-e29b-41d4-a716-446655440030"

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


def _count_result(n):
    r = MagicMock()
    r.scalar = MagicMock(return_value=n)
    return r


# ---------------------------------------------------------------------------
# Domain mock builders
# ---------------------------------------------------------------------------

def _make_ch_mock(**kw):
    ch = MagicMock()
    ch.id = uuid.UUID(_CH_ID)
    ch.company_id = "company-001"
    ch.is_accessible_by_user = MagicMock(return_value=True)
    for k, v in kw.items():
        setattr(ch, k, v)
    return ch


def _make_member_mock(**kw):
    m = MagicMock()
    m.id = uuid.UUID(_MEMBER_ID)
    m.user_id = uuid.UUID(_USER_ID)
    m.channel_id = uuid.UUID(_CH_ID)
    m.level = "channel"
    m.role = "member"
    m.is_active = True
    m.permissions = {}
    m.invited_by = None
    m.joined_at = None
    m.created_at = None
    m.updated_at = None
    for k, v in kw.items():
        setattr(m, k, v)
    return m


def _make_conn_mock(**kw):
    conn = MagicMock()
    conn.id = uuid.UUID(_CONN_ID)
    conn.app_id = uuid.UUID(_APP_ID)
    conn.channel_id = uuid.UUID(_CH_ID)
    conn.level = "channel"
    conn.connected_by = _USER_ID
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
    for k, v in kw.items():
        setattr(conn, k, v)
    return conn


def _make_app_mock():
    a = MagicMock()
    a.id = uuid.UUID(_APP_ID)
    a.is_active = True
    return a


def _make_user_mock():
    u = MagicMock()
    u.id = _USER_ID
    u.name = "Admin User"
    u.email_id = "admin@example.com"
    u.avatar_url = None
    return u


# ---------------------------------------------------------------------------
# Client factory
# ---------------------------------------------------------------------------

def _make_ch_client(mock_db):
    from app.routes.gg_channels import router as ch_router
    app = FastAPI()
    app.include_router(ch_router, prefix="/gg-channels")
    app.dependency_overrides[get_db] = lambda: mock_db
    return TestClient(app)


# ---------------------------------------------------------------------------
# TestListChannelMembers
# ---------------------------------------------------------------------------

class TestListChannelMembers:

    @pytest.mark.unit
    def test_list_empty(self, mock_db, admin_user):
        """Channel found, count=0, members=[] → 200 with empty members list."""
        ch = _make_ch_mock()
        mock_db.execute = AsyncMock(side_effect=[
            _scalar(ch),          # channel lookup
            _count_result(0),     # total count
            _scalars_result([]),  # members list
        ])
        client = _make_ch_client(mock_db)
        with patch("app.routes.gg_channels.get_current_user_required", new=AsyncMock(return_value=admin_user)):
            resp = client.get(f"/gg-channels/{_CH_ID}/members")
        assert resp.status_code == 200
        assert resp.json()["members"] == []

    @pytest.mark.unit
    def test_list_with_members(self, mock_db, admin_user):
        """Channel found, count=1, members=[member] → 200 with one member."""
        ch = _make_ch_mock()
        member = _make_member_mock()
        mock_db.execute = AsyncMock(side_effect=[
            _scalar(ch),               # channel lookup
            _count_result(1),          # total count
            _scalars_result([member]), # members list
        ])
        client = _make_ch_client(mock_db)
        with patch("app.routes.gg_channels.get_current_user_required", new=AsyncMock(return_value=admin_user)):
            resp = client.get(f"/gg-channels/{_CH_ID}/members")
        assert resp.status_code == 200
        assert len(resp.json()["members"]) == 1

    @pytest.mark.unit
    def test_list_channel_not_found(self, mock_db, admin_user):
        """Channel not found → 404."""
        mock_db.execute = AsyncMock(return_value=_scalar(None))
        client = _make_ch_client(mock_db)
        with patch("app.routes.gg_channels.get_current_user_required", new=AsyncMock(return_value=admin_user)):
            resp = client.get(f"/gg-channels/{_CH_ID}/members")
        assert resp.status_code == 404

    @pytest.mark.unit
    def test_list_invalid_uuid(self, mock_db, admin_user):
        """Invalid channel_id UUID → 400."""
        client = _make_ch_client(mock_db)
        with patch("app.routes.gg_channels.get_current_user_required", new=AsyncMock(return_value=admin_user)):
            resp = client.get("/gg-channels/not-a-uuid/members")
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# TestAddChannelMember
# ---------------------------------------------------------------------------

class TestAddChannelMember:

    @pytest.mark.unit
    def test_add_success(self, mock_db, admin_user):
        """Channel found, accessible → 201 with member created."""
        ch = _make_ch_mock()
        member = _make_member_mock()
        mock_db.execute = AsyncMock(return_value=_scalar(ch))
        mock_db.refresh = AsyncMock(side_effect=lambda obj: None)
        client = _make_ch_client(mock_db)
        with patch("app.routes.gg_channels.get_current_user_required", new=AsyncMock(return_value=admin_user)):
            with patch("app.routes.gg_channels.GGMember", return_value=member):
                resp = client.post(
                    f"/gg-channels/{_CH_ID}/members",
                    json={"user_id": _USER_ID, "role": "member"},
                )
        assert resp.status_code == 201

    @pytest.mark.unit
    def test_add_channel_not_found(self, mock_db, admin_user):
        """Channel not found → 404."""
        mock_db.execute = AsyncMock(return_value=_scalar(None))
        client = _make_ch_client(mock_db)
        with patch("app.routes.gg_channels.get_current_user_required", new=AsyncMock(return_value=admin_user)):
            resp = client.post(
                f"/gg-channels/{_CH_ID}/members",
                json={"user_id": _USER_ID, "role": "member"},
            )
        assert resp.status_code == 404

    @pytest.mark.unit
    def test_add_access_denied(self, mock_db, admin_user):
        """Channel found but is_accessible_by_user=False → 403."""
        ch = _make_ch_mock()
        ch.is_accessible_by_user = MagicMock(return_value=False)
        mock_db.execute = AsyncMock(return_value=_scalar(ch))
        client = _make_ch_client(mock_db)
        with patch("app.routes.gg_channels.get_current_user_required", new=AsyncMock(return_value=admin_user)):
            resp = client.post(
                f"/gg-channels/{_CH_ID}/members",
                json={"user_id": _USER_ID, "role": "member"},
            )
        assert resp.status_code == 403

    @pytest.mark.unit
    def test_add_invalid_uuid(self, mock_db, admin_user):
        """Invalid channel_id UUID → 400."""
        client = _make_ch_client(mock_db)
        with patch("app.routes.gg_channels.get_current_user_required", new=AsyncMock(return_value=admin_user)):
            resp = client.post(
                "/gg-channels/not-a-uuid/members",
                json={"user_id": _USER_ID, "role": "member"},
            )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# TestUpdateChannelMember
# ---------------------------------------------------------------------------

class TestUpdateChannelMember:

    @pytest.mark.unit
    def test_update_role(self, mock_db, admin_user):
        """Member found → role updated, 200."""
        member = _make_member_mock()
        mock_db.execute = AsyncMock(return_value=_scalar(member))
        client = _make_ch_client(mock_db)
        with patch("app.routes.gg_channels.get_current_user_required", new=AsyncMock(return_value=admin_user)):
            resp = client.put(
                f"/gg-channels/{_CH_ID}/members/{_USER_ID}",
                json={"role": "admin"},
            )
        assert resp.status_code == 200

    @pytest.mark.unit
    def test_update_member_not_found(self, mock_db, admin_user):
        """Member not found → 404."""
        mock_db.execute = AsyncMock(return_value=_scalar(None))
        client = _make_ch_client(mock_db)
        with patch("app.routes.gg_channels.get_current_user_required", new=AsyncMock(return_value=admin_user)):
            resp = client.put(
                f"/gg-channels/{_CH_ID}/members/{_USER_ID}",
                json={"role": "admin"},
            )
        assert resp.status_code == 404

    @pytest.mark.unit
    def test_update_invalid_uuid(self, mock_db, admin_user):
        """Invalid channel_id UUID → 400."""
        client = _make_ch_client(mock_db)
        with patch("app.routes.gg_channels.get_current_user_required", new=AsyncMock(return_value=admin_user)):
            resp = client.put(
                f"/gg-channels/not-a-uuid/members/{_USER_ID}",
                json={"role": "admin"},
            )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# TestRemoveChannelMember
# ---------------------------------------------------------------------------

class TestRemoveChannelMember:

    @pytest.mark.unit
    def test_remove_success(self, mock_db, admin_user):
        """Member found → deleted, 200."""
        member = _make_member_mock()
        mock_db.execute = AsyncMock(return_value=_scalar(member))
        mock_db.delete = AsyncMock()
        client = _make_ch_client(mock_db)
        with patch("app.routes.gg_channels.get_current_user_required", new=AsyncMock(return_value=admin_user)):
            resp = client.delete(f"/gg-channels/{_CH_ID}/members/{_USER_ID}")
        assert resp.status_code == 200

    @pytest.mark.unit
    def test_remove_not_found(self, mock_db, admin_user):
        """Member not found → 404."""
        mock_db.execute = AsyncMock(return_value=_scalar(None))
        client = _make_ch_client(mock_db)
        with patch("app.routes.gg_channels.get_current_user_required", new=AsyncMock(return_value=admin_user)):
            resp = client.delete(f"/gg-channels/{_CH_ID}/members/{_USER_ID}")
        assert resp.status_code == 404

    @pytest.mark.unit
    def test_remove_invalid_uuid(self, mock_db, admin_user):
        """Invalid channel_id UUID → 400."""
        client = _make_ch_client(mock_db)
        with patch("app.routes.gg_channels.get_current_user_required", new=AsyncMock(return_value=admin_user)):
            resp = client.delete(f"/gg-channels/not-a-uuid/members/{_USER_ID}")
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# TestListChannelAppConnections
# ---------------------------------------------------------------------------

class TestListChannelAppConnections:

    @pytest.mark.unit
    def test_list_empty(self, mock_db, admin_user):
        """Channel found, count=0, rows=[] → 200 with empty connections."""
        ch = _make_ch_mock()
        mock_db.execute = AsyncMock(side_effect=[
            _scalar(ch),          # channel lookup
            _count_result(0),     # total count
            _scalars_result([]),  # rows
            # no user fetch when rows is empty
        ])
        client = _make_ch_client(mock_db)
        with patch("app.routes.gg_channels.get_current_user_required", new=AsyncMock(return_value=admin_user)):
            resp = client.get(f"/gg-channels/{_CH_ID}/app-connections")
        assert resp.status_code == 200
        assert resp.json()["connections"] == []

    @pytest.mark.unit
    def test_list_with_connections(self, mock_db, admin_user):
        """Channel found, count=1, rows=[conn], users=[user] → 200, len=1."""
        ch = _make_ch_mock()
        conn = _make_conn_mock()
        user = _make_user_mock()
        mock_db.execute = AsyncMock(side_effect=[
            _scalar(ch),               # channel lookup
            _count_result(1),          # total count
            _scalars_result([conn]),   # rows
            _scalars_result([user]),   # users batch
        ])
        client = _make_ch_client(mock_db)
        with patch("app.routes.gg_channels.get_current_user_required", new=AsyncMock(return_value=admin_user)):
            resp = client.get(f"/gg-channels/{_CH_ID}/app-connections")
        assert resp.status_code == 200
        assert len(resp.json()["connections"]) == 1

    @pytest.mark.unit
    def test_list_channel_not_found(self, mock_db, admin_user):
        """Channel not found → 404."""
        mock_db.execute = AsyncMock(return_value=_scalar(None))
        client = _make_ch_client(mock_db)
        with patch("app.routes.gg_channels.get_current_user_required", new=AsyncMock(return_value=admin_user)):
            resp = client.get(f"/gg-channels/{_CH_ID}/app-connections")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# TestConnectChannelApp
# ---------------------------------------------------------------------------

class TestConnectChannelApp:

    @pytest.mark.unit
    def test_connect_success(self, mock_db, admin_user):
        """Channel found, app found, no existing connection → 201."""
        ch = _make_ch_mock()
        app_mock = _make_app_mock()
        conn = _make_conn_mock()
        mock_db.execute = AsyncMock(side_effect=[
            _scalar(ch),       # channel lookup
            _scalar(app_mock), # app lookup
            _scalar(None),     # no existing connection
        ])
        mock_db.refresh = AsyncMock(side_effect=lambda obj: None)
        client = _make_ch_client(mock_db)
        with patch("app.routes.gg_channels.get_current_user_required", new=AsyncMock(return_value=admin_user)):
            resp = client.post(
                f"/gg-channels/{_CH_ID}/app-connections",
                json={
                    "app_id": _APP_ID,
                    "connection_name": "Test Connection",
                    "connection_status": "active",
                },
            )
        assert resp.status_code == 201

    @pytest.mark.unit
    def test_connect_channel_not_found(self, mock_db, admin_user):
        """Channel not found → 404."""
        mock_db.execute = AsyncMock(return_value=_scalar(None))
        client = _make_ch_client(mock_db)
        with patch("app.routes.gg_channels.get_current_user_required", new=AsyncMock(return_value=admin_user)):
            resp = client.post(
                f"/gg-channels/{_CH_ID}/app-connections",
                json={
                    "app_id": _APP_ID,
                    "connection_name": "Test Connection",
                    "connection_status": "active",
                },
            )
        assert resp.status_code == 404

    @pytest.mark.unit
    def test_connect_app_not_found(self, mock_db, admin_user):
        """App not found or inactive → 404."""
        ch = _make_ch_mock()
        mock_db.execute = AsyncMock(side_effect=[
            _scalar(ch),    # channel lookup
            _scalar(None),  # app not found
        ])
        client = _make_ch_client(mock_db)
        with patch("app.routes.gg_channels.get_current_user_required", new=AsyncMock(return_value=admin_user)):
            resp = client.post(
                f"/gg-channels/{_CH_ID}/app-connections",
                json={
                    "app_id": _APP_ID,
                    "connection_name": "Test Connection",
                    "connection_status": "active",
                },
            )
        assert resp.status_code == 404

    @pytest.mark.unit
    def test_connect_already_connected(self, mock_db, admin_user):
        """App already connected to channel → 409."""
        ch = _make_ch_mock()
        app_mock = _make_app_mock()
        existing = _make_conn_mock()
        mock_db.execute = AsyncMock(side_effect=[
            _scalar(ch),        # channel lookup
            _scalar(app_mock),  # app lookup
            _scalar(existing),  # existing connection found
        ])
        client = _make_ch_client(mock_db)
        with patch("app.routes.gg_channels.get_current_user_required", new=AsyncMock(return_value=admin_user)):
            resp = client.post(
                f"/gg-channels/{_CH_ID}/app-connections",
                json={
                    "app_id": _APP_ID,
                    "connection_name": "Test Connection",
                    "connection_status": "active",
                },
            )
        assert resp.status_code == 409

    @pytest.mark.unit
    def test_connect_access_denied(self, mock_db, admin_user):
        """Channel found but is_accessible_by_user=False → 403."""
        ch = _make_ch_mock()
        ch.is_accessible_by_user = MagicMock(return_value=False)
        mock_db.execute = AsyncMock(return_value=_scalar(ch))
        client = _make_ch_client(mock_db)
        with patch("app.routes.gg_channels.get_current_user_required", new=AsyncMock(return_value=admin_user)):
            resp = client.post(
                f"/gg-channels/{_CH_ID}/app-connections",
                json={
                    "app_id": _APP_ID,
                    "connection_name": "Test Connection",
                    "connection_status": "active",
                },
            )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# TestUpdateChannelAppConnection
# ---------------------------------------------------------------------------

class TestUpdateChannelAppConnection:

    @pytest.mark.unit
    def test_update_success(self, mock_db, admin_user):
        """Channel found, connection found, commit/refresh, user lookup → 200."""
        ch = _make_ch_mock()
        conn = _make_conn_mock()
        user = _make_user_mock()
        mock_db.execute = AsyncMock(side_effect=[
            _scalar(ch),    # channel lookup
            _scalar(conn),  # connection lookup
            _scalar(user),  # connector user lookup (after commit/refresh)
        ])
        client = _make_ch_client(mock_db)
        with patch("app.routes.gg_channels.get_current_user_required", new=AsyncMock(return_value=admin_user)):
            resp = client.put(
                f"/gg-channels/{_CH_ID}/app-connections/{_CONN_ID}",
                json={"connection_name": "Updated"},
            )
        assert resp.status_code == 200

    @pytest.mark.unit
    def test_update_connection_not_found(self, mock_db, admin_user):
        """Connection not found → 404."""
        ch = _make_ch_mock()
        mock_db.execute = AsyncMock(side_effect=[
            _scalar(ch),    # channel lookup
            _scalar(None),  # connection not found
        ])
        client = _make_ch_client(mock_db)
        with patch("app.routes.gg_channels.get_current_user_required", new=AsyncMock(return_value=admin_user)):
            resp = client.put(
                f"/gg-channels/{_CH_ID}/app-connections/{_CONN_ID}",
                json={"connection_name": "Updated"},
            )
        assert resp.status_code == 404

    @pytest.mark.unit
    def test_update_access_denied(self, mock_db, admin_user):
        """Channel found but is_accessible_by_user=False → 403."""
        ch = _make_ch_mock()
        ch.is_accessible_by_user = MagicMock(return_value=False)
        mock_db.execute = AsyncMock(return_value=_scalar(ch))
        client = _make_ch_client(mock_db)
        with patch("app.routes.gg_channels.get_current_user_required", new=AsyncMock(return_value=admin_user)):
            resp = client.put(
                f"/gg-channels/{_CH_ID}/app-connections/{_CONN_ID}",
                json={"connection_name": "Updated"},
            )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# TestDisconnectChannelApp
# ---------------------------------------------------------------------------

class TestDisconnectChannelApp:

    @pytest.mark.unit
    def test_disconnect_success(self, mock_db, admin_user):
        """Channel found, connection found → deleted, 200."""
        ch = _make_ch_mock()
        conn = _make_conn_mock()
        mock_db.execute = AsyncMock(side_effect=[
            _scalar(ch),    # channel lookup
            _scalar(conn),  # connection lookup
        ])
        mock_db.delete = AsyncMock()
        client = _make_ch_client(mock_db)
        with patch("app.routes.gg_channels.get_current_user_required", new=AsyncMock(return_value=admin_user)):
            resp = client.delete(f"/gg-channels/{_CH_ID}/app-connections/{_CONN_ID}")
        assert resp.status_code == 200

    @pytest.mark.unit
    def test_disconnect_not_found(self, mock_db, admin_user):
        """Connection not found → 404."""
        ch = _make_ch_mock()
        mock_db.execute = AsyncMock(side_effect=[
            _scalar(ch),    # channel lookup
            _scalar(None),  # connection not found
        ])
        client = _make_ch_client(mock_db)
        with patch("app.routes.gg_channels.get_current_user_required", new=AsyncMock(return_value=admin_user)):
            resp = client.delete(f"/gg-channels/{_CH_ID}/app-connections/{_CONN_ID}")
        assert resp.status_code == 404

    @pytest.mark.unit
    def test_disconnect_access_denied(self, mock_db, admin_user):
        """Channel found but is_accessible_by_user=False → 403."""
        ch = _make_ch_mock()
        ch.is_accessible_by_user = MagicMock(return_value=False)
        mock_db.execute = AsyncMock(return_value=_scalar(ch))
        client = _make_ch_client(mock_db)
        with patch("app.routes.gg_channels.get_current_user_required", new=AsyncMock(return_value=admin_user)):
            resp = client.delete(f"/gg-channels/{_CH_ID}/app-connections/{_CONN_ID}")
        assert resp.status_code == 403
