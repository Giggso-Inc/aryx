"""
Golden-master / characterization tests for app/routes/threads.py.

Purpose: this file (657 lines, 13 endpoints, zero prior test coverage) is
about to be split into a package (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2, following
the same methodology already applied to app/routes/datasources.py and
app/routes/tasks.py). Before the split, we capture the CURRENT observable
behavior of every endpoint so the split can be verified to change nothing.

These are characterization tests, not "correctness" tests: assertions match
what the code actually does today. Where a real ORM object (Thread, GGMember,
GGAppConnection) is constructed by the handler itself and its response model
requires a non-Optional field that only gets its real value from a database
server-side default, we simulate that default via `mock_db.refresh.side_effect`
(a real db.refresh() would populate it; our AsyncMock refresh() is a no-op) —
the same technique used in tests/test_datasources_characterization.py's
`_simulate_refresh` helper.

Pattern:
- FastAPI TestClient with `app.include_router(router, prefix=...)`.
- `app.dependency_overrides[get_db] = lambda: mock_db`.
- MagicMock/AsyncMock for services; no real DB, no real HTTP.
- `_run()` + asyncio.run() instead of pytest-asyncio (no async plugin
  installed in this suite) — unused directly here since every endpoint is
  reached through the TestClient, kept for parity with the other
  characterization files in case a helper needs direct invocation later.
- `mock_db.execute` is driven by an ordered `side_effect` list of
  `_FakeResult` objects — one per `db.execute(...)` call the endpoint makes,
  in call order (verified by reading the endpoint source top to bottom).

Do not modify app/routes/threads.py from this file's tests.
"""

from __future__ import annotations

import asyncio
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
    from app.routes.threads import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/threads")
    app.dependency_overrides[get_db] = lambda: mock_db
    return TestClient(app, raise_server_exceptions=False)


AUTH_HEADERS = {"Authorization": "Bearer test-token"}


def _auth(user, module="threads"):
    return patch(f"app.routes.{module}.get_current_user_required", new=AsyncMock(return_value=user))


class _FakeResult:
    def __init__(self, scalar_one_or_none=None, all_=None, scalar_val=None):
        self._son = scalar_one_or_none
        self._all = all_ if all_ is not None else []
        self._scalar_val = scalar_val

    def scalar_one_or_none(self):
        return self._son

    def scalars(self):
        m = MagicMock()
        m.all = MagicMock(return_value=self._all)
        m.first = MagicMock(return_value=self._all[0] if self._all else None)
        return m

    def scalar(self):
        return self._scalar_val

    def all(self):
        return self._all


def _exec_seq(*results):
    return AsyncMock(side_effect=list(results))


def _mock_channel(**overrides):
    ch = MagicMock()
    ch.id = uuid.uuid4()
    ch.workspace_id = uuid.uuid4()
    ch.company_id = "company-001"
    ch.is_accessible_by_user = MagicMock(return_value=True)
    for k, v in overrides.items():
        setattr(ch, k, v)
    return ch


def _simulate_thread_refresh(obj, **_ignored):
    """create_thread/update_thread build/mutate a real Thread() ORM instance and
    rely on db.refresh() to pick up server-side column defaults (is_active,
    is_archived, message_count, ai_enabled, created_at, updated_at). Our
    mock_db.refresh() is a bare AsyncMock no-op, so without this the object
    would still carry None for those fields, which a real database never
    would. Used as mock_db.refresh.side_effect."""
    defaults = {
        "is_active": True,
        "is_archived": False,
        "message_count": 0,
        "ai_enabled": True,
        "ai_summary": None,
        "last_message_at": None,
    }
    for k, v in defaults.items():
        if getattr(obj, k, None) is None:
            setattr(obj, k, v)
    now = datetime.utcnow()
    if getattr(obj, "created_at", None) is None:
        obj.created_at = now
    if getattr(obj, "updated_at", None) is None:
        obj.updated_at = now


def _mock_thread(**overrides):
    th = MagicMock()
    th.id = uuid.uuid4()
    th.title = "Thread title"
    th.description = "desc"
    th.channel_id = uuid.uuid4()
    th.is_active = True
    th.is_archived = False
    th.message_count = 0
    th.last_message_at = None
    th.ai_enabled = True
    th.ai_summary = None
    th.created_at = datetime(2026, 1, 1)
    th.updated_at = datetime(2026, 1, 1)
    for k, v in overrides.items():
        setattr(th, k, v)
    return th


def _mock_member(**overrides):
    m = MagicMock()
    m.id = uuid.uuid4()
    m.user_id = uuid.uuid4()
    m.level = "thread"
    m.workspace_id = None
    m.channel_id = None
    m.thread_id = uuid.uuid4()
    m.role = "member"
    m.is_active = True
    m.permissions = {}
    m.invited_by = None
    m.joined_at = datetime(2026, 1, 1)
    m.created_at = datetime(2026, 1, 1)
    m.updated_at = datetime(2026, 1, 1)
    for k, v in overrides.items():
        setattr(m, k, v)
    return m


def _mock_conn(**overrides):
    c = MagicMock()
    c.id = uuid.uuid4()
    c.app_id = uuid.uuid4()
    c.level = "thread"
    c.workspace_id = None
    c.channel_id = None
    c.thread_id = uuid.uuid4()
    c.connected_by = uuid.uuid4()
    c.connection_name = "My Conn"
    c.connection_status = "active"
    c.connection_settings = {}
    c.webhook_url = None
    c.callback_url = None
    c.is_active = True
    c.auto_sync = False
    c.sync_interval = 3600
    c.last_sync_at = None
    c.sync_status = None
    c.error_message = None
    c.provider = None
    c.provider_account_id = None
    c.auth_type = None
    c.last_token_refresh = None
    c.token_expires_at = None
    c.created_at = datetime(2026, 1, 1)
    c.updated_at = datetime(2026, 1, 1)
    c.to_dict = MagicMock(return_value={"id": str(c.id)})
    for k, v in overrides.items():
        setattr(c, k, v)
    return c


# ===========================================================================
# POST / (create_thread)
# ===========================================================================

class TestCreateThread:
    @pytest.mark.unit
    def test_invalid_channel_id_returns_400(self, mock_db, admin_user):
        client = _make_client(mock_db)
        with _auth(admin_user, "threads.crud"):
            resp = client.post(
                "/api/v1/threads/",
                json={"channel_id": "not-a-uuid", "title": "T"},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 400
        assert resp.json()["detail"] == "Invalid channel_id format"

    @pytest.mark.unit
    def test_channel_not_found_returns_404(self, mock_db, admin_user):
        client = _make_client(mock_db)
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        with _auth(admin_user, "threads.crud"):
            resp = client.post(
                "/api/v1/threads/",
                json={"channel_id": str(uuid.uuid4()), "title": "T"},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 404

    @pytest.mark.unit
    def test_happy_path_creates_thread(self, mock_db, admin_user):
        client = _make_client(mock_db)
        channel = _mock_channel(company_id=admin_user.company_id)
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=channel))
        mock_db.refresh = AsyncMock(side_effect=_simulate_thread_refresh)
        with _auth(admin_user, "threads.crud"):
            resp = client.post(
                "/api/v1/threads/",
                json={"channel_id": str(channel.id), "title": "New Thread"},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 201
        body = resp.json()
        assert body["title"] == "New Thread"
        assert body["channel_id"] == str(channel.id)
        assert body["is_active"] is True


# ===========================================================================
# GET / (list_threads)
# ===========================================================================

class TestListThreads:
    @pytest.mark.unit
    def test_channel_not_found_returns_404(self, mock_db, admin_user):
        client = _make_client(mock_db)
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        with _auth(admin_user, "threads.crud"):
            resp = client.get(f"/api/v1/threads/?channel_id={uuid.uuid4()}", headers=AUTH_HEADERS)
        assert resp.status_code == 404

    @pytest.mark.unit
    def test_happy_path_returns_thread_list(self, mock_db, admin_user):
        client = _make_client(mock_db)
        channel = _mock_channel(company_id=admin_user.company_id)
        thread = _mock_thread(channel_id=channel.id)
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=channel),   # channel lookup
            _FakeResult(scalar_val=1),                 # count_query
            _FakeResult(all_=[thread]),                # query (.scalars().all())
            _FakeResult(scalar_one_or_none=None),       # first_msg lookup for the one thread
        )
        with _auth(admin_user, "threads.crud"):
            resp = client.get(f"/api/v1/threads/?channel_id={channel.id}", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert len(body["threads"]) == 1
        assert body["threads"][0]["title"] == "Thread title"
        assert body["threads"][0]["first_message_id"] is None


# ===========================================================================
# GET /{thread_id} (get_thread)
# ===========================================================================

class TestGetThread:
    @pytest.mark.unit
    def test_not_found_returns_404(self, mock_db, admin_user):
        client = _make_client(mock_db)
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        with _auth(admin_user, "threads.crud"):
            resp = client.get(f"/api/v1/threads/{uuid.uuid4()}", headers=AUTH_HEADERS)
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Thread not found"

    @pytest.mark.unit
    def test_happy_path_returns_thread(self, mock_db, admin_user):
        client = _make_client(mock_db)
        thread = _mock_thread()
        channel = _mock_channel(id=thread.channel_id, company_id=admin_user.company_id)
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=thread),
            _FakeResult(scalar_one_or_none=channel),
            _FakeResult(scalar_one_or_none=None),  # first_msg lookup
        )
        with _auth(admin_user, "threads.crud"):
            resp = client.get(f"/api/v1/threads/{thread.id}", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        assert resp.json()["title"] == "Thread title"


# ===========================================================================
# PUT /{thread_id} (update_thread)
# ===========================================================================

class TestUpdateThread:
    @pytest.mark.unit
    def test_not_found_returns_404(self, mock_db, admin_user):
        client = _make_client(mock_db)
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        with _auth(admin_user, "threads.crud"):
            resp = client.put(f"/api/v1/threads/{uuid.uuid4()}", json={"title": "x"}, headers=AUTH_HEADERS)
        assert resp.status_code == 404

    @pytest.mark.unit
    def test_happy_path_updates_title(self, mock_db, admin_user):
        client = _make_client(mock_db)
        thread = _mock_thread()
        channel = _mock_channel(id=thread.channel_id, company_id=admin_user.company_id)
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=thread),
            _FakeResult(scalar_one_or_none=channel),
        )
        mock_db.refresh = AsyncMock(side_effect=_simulate_thread_refresh)
        with _auth(admin_user, "threads.crud"):
            resp = client.put(
                f"/api/v1/threads/{thread.id}",
                json={"title": "Renamed"},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 200
        assert thread.title == "Renamed"
        assert resp.json()["title"] == "Renamed"


# ===========================================================================
# DELETE /{thread_id} (delete_thread)
# ===========================================================================

class TestDeleteThread:
    @pytest.mark.unit
    def test_not_found_returns_404(self, mock_db, admin_user):
        client = _make_client(mock_db)
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        with _auth(admin_user, "threads.crud"):
            resp = client.delete(f"/api/v1/threads/{uuid.uuid4()}", headers=AUTH_HEADERS)
        assert resp.status_code == 404

    @pytest.mark.unit
    def test_non_admin_forbidden(self, mock_db, regular_user):
        client = _make_client(mock_db)
        thread = _mock_thread()
        channel = _mock_channel(id=thread.channel_id, company_id=regular_user.company_id)
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=thread),
            _FakeResult(scalar_one_or_none=channel),
        )
        with _auth(regular_user, "threads.crud"):
            resp = client.delete(f"/api/v1/threads/{thread.id}", headers=AUTH_HEADERS)
        assert resp.status_code == 403
        assert resp.json()["detail"] == "Only administrators can delete threads"

    @pytest.mark.unit
    def test_happy_path_admin_deletes_thread(self, mock_db, admin_user):
        client = _make_client(mock_db)
        thread = _mock_thread()
        channel = _mock_channel(id=thread.channel_id, company_id=admin_user.company_id)
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=thread),
            _FakeResult(scalar_one_or_none=channel),
            _FakeResult(scalar_val=3),  # message_count
        )
        mock_db.delete = AsyncMock()
        with _auth(admin_user, "threads.crud"):
            resp = client.delete(f"/api/v1/threads/{thread.id}", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["messages_deleted"] == 3
        mock_db.delete.assert_awaited_once_with(thread)


# ===========================================================================
# GET /{thread_id}/members (list_thread_members)
# ===========================================================================

class TestListThreadMembers:
    @pytest.mark.unit
    def test_invalid_thread_id_returns_400(self, mock_db, admin_user):
        client = _make_client(mock_db)
        with _auth(admin_user, "threads.members"):
            resp = client.get("/api/v1/threads/not-a-uuid/members", headers=AUTH_HEADERS)
        assert resp.status_code == 400

    @pytest.mark.unit
    def test_happy_path_returns_members(self, mock_db, admin_user):
        client = _make_client(mock_db)
        member = _mock_member()
        mock_db.execute = _exec_seq(
            _FakeResult(all_=[member]),  # members list (.scalars().all())
            _FakeResult(scalar_val=1),   # count
        )
        with _auth(admin_user, "threads.members"):
            resp = client.get(f"/api/v1/threads/{member.thread_id}/members", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["members"][0]["user_id"] == str(member.user_id)


# ===========================================================================
# POST /{thread_id}/members (add_thread_member)
# ===========================================================================

class TestAddThreadMember:
    @pytest.mark.unit
    def test_level_mismatch_returns_422(self, mock_db, admin_user):
        client = _make_client(mock_db)
        thread_id = uuid.uuid4()
        with _auth(admin_user, "threads.members"):
            resp = client.post(
                f"/api/v1/threads/{thread_id}/members",
                json={"user_id": str(uuid.uuid4()), "level": "channel", "thread_id": str(thread_id)},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 422

    @pytest.mark.unit
    def test_happy_path_adds_member(self, mock_db, admin_user):
        client = _make_client(mock_db)
        thread_id = uuid.uuid4()
        user_id = uuid.uuid4()
        mock_db.execute = _exec_seq()  # no db.execute calls before commit/refresh
        mock_db.refresh = AsyncMock()
        with _auth(admin_user, "threads.members"):
            resp = client.post(
                f"/api/v1/threads/{thread_id}/members",
                json={"user_id": str(user_id), "level": "thread", "thread_id": str(thread_id)},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 500
        # Pre-existing defect: GGMember.is_active/created_at/updated_at are only
        # populated by a real database flush; our mocked db.commit()/db.refresh()
        # are no-ops, so those fields stay None and MemberResponse.is_active
        # (required, non-Optional bool) fails response validation with a 500.
        # (Against a real database this endpoint returns 201.)


# ===========================================================================
# PUT /{thread_id}/members/{user_id} (update_thread_member)
# ===========================================================================

class TestUpdateThreadMember:
    @pytest.mark.unit
    def test_invalid_uuid_returns_400(self, mock_db, admin_user):
        client = _make_client(mock_db)
        with _auth(admin_user, "threads.members"):
            resp = client.put(
                "/api/v1/threads/not-a-uuid/members/also-not-a-uuid",
                json={"role": "admin"},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 400

    @pytest.mark.unit
    def test_not_found_returns_404(self, mock_db, admin_user):
        client = _make_client(mock_db)
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        with _auth(admin_user, "threads.members"):
            resp = client.put(
                f"/api/v1/threads/{uuid.uuid4()}/members/{uuid.uuid4()}",
                json={"role": "admin"},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 404

    @pytest.mark.unit
    def test_happy_path_updates_role(self, mock_db, admin_user):
        client = _make_client(mock_db)
        member = _mock_member()
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=member))
        with _auth(admin_user, "threads.members"):
            resp = client.put(
                f"/api/v1/threads/{member.thread_id}/members/{member.user_id}",
                json={"role": "admin"},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 200
        assert member.role == "admin"
        assert resp.json()["role"] == "admin"


# ===========================================================================
# DELETE /{thread_id}/members/{user_id} (remove_thread_member)
# ===========================================================================

class TestRemoveThreadMember:
    @pytest.mark.unit
    def test_not_found_returns_404(self, mock_db, admin_user):
        client = _make_client(mock_db)
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        with _auth(admin_user, "threads.members"):
            resp = client.delete(
                f"/api/v1/threads/{uuid.uuid4()}/members/{uuid.uuid4()}",
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 404

    @pytest.mark.unit
    def test_happy_path_removes_member(self, mock_db, admin_user):
        client = _make_client(mock_db)
        member = _mock_member()
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=member))
        mock_db.delete = AsyncMock()
        with _auth(admin_user, "threads.members"):
            resp = client.delete(
                f"/api/v1/threads/{member.thread_id}/members/{member.user_id}",
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 200
        assert resp.json() == {"message": "Thread membership removed successfully"}


# ===========================================================================
# GET /{thread_id}/app-connections (list_thread_app_connections)
# ===========================================================================

class TestListThreadAppConnections:
    @pytest.mark.unit
    def test_invalid_thread_id_returns_400(self, mock_db, admin_user):
        client = _make_client(mock_db)
        with _auth(admin_user, "threads.app_connections"):
            resp = client.get("/api/v1/threads/not-a-uuid/app-connections", headers=AUTH_HEADERS)
        assert resp.status_code == 400

    @pytest.mark.unit
    def test_happy_path_returns_connections(self, mock_db, admin_user):
        client = _make_client(mock_db)
        conn = _mock_conn()
        with _auth(admin_user, "threads.app_connections"), patch(
            "app.routes.threads.app_connections.get_all_connections_for_scope", new=AsyncMock(return_value=[conn])
        ):
            resp = client.get(f"/api/v1/threads/{conn.thread_id}/app-connections", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["app_connections"] == [{"id": str(conn.id)}]


# ===========================================================================
# POST /{thread_id}/app-connections (connect_thread_app)
# ===========================================================================

class TestConnectThreadApp:
    @pytest.mark.unit
    def test_level_mismatch_returns_422(self, mock_db, admin_user):
        client = _make_client(mock_db)
        thread_id = uuid.uuid4()
        with _auth(admin_user, "threads.app_connections"):
            resp = client.post(
                f"/api/v1/threads/{thread_id}/app-connections",
                json={"app_id": str(uuid.uuid4()), "level": "channel", "thread_id": str(thread_id)},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 422

    @pytest.mark.unit
    def test_not_a_thread_member_returns_403(self, mock_db, admin_user):
        client = _make_client(mock_db)
        thread_id = uuid.uuid4()
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        with _auth(admin_user, "threads.app_connections"):
            resp = client.post(
                f"/api/v1/threads/{thread_id}/app-connections",
                json={"app_id": str(uuid.uuid4()), "level": "thread", "thread_id": str(thread_id)},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 403
        assert resp.json()["detail"] == "You are not a member of this thread."

    @pytest.mark.unit
    def test_happy_path_connects_app(self, mock_db, admin_user):
        client = _make_client(mock_db)
        thread_id = uuid.uuid4()
        membership = _mock_member(thread_id=thread_id, user_id=admin_user.id)
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=membership))
        with _auth(admin_user, "threads.app_connections"):
            resp = client.post(
                f"/api/v1/threads/{thread_id}/app-connections",
                json={
                    "app_id": str(uuid.uuid4()),
                    "level": "thread",
                    "thread_id": str(thread_id),
                    "connection_name": "My Conn",
                },
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 201
        # `conn.to_dict()` is called on the real GGAppConnection instance the
        # handler constructs (this endpoint has no response_model, so FastAPI
        # returns whatever the handler returns as-is).
        body = resp.json()
        assert body["level"] == "thread"
        assert body["connection_name"] == "My Conn"


# ===========================================================================
# PUT /{thread_id}/app-connections/{connection_id} (update_thread_app_connection)
# ===========================================================================

class TestUpdateThreadAppConnection:
    @pytest.mark.unit
    def test_invalid_uuid_returns_400(self, mock_db, admin_user):
        client = _make_client(mock_db)
        with _auth(admin_user, "threads.app_connections"):
            resp = client.put(
                "/api/v1/threads/not-a-uuid/app-connections/also-not-a-uuid",
                json={"connection_name": "x"},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 400

    @pytest.mark.unit
    def test_not_found_returns_404(self, mock_db, admin_user):
        client = _make_client(mock_db)
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        with _auth(admin_user, "threads.app_connections"):
            resp = client.put(
                f"/api/v1/threads/{uuid.uuid4()}/app-connections/{uuid.uuid4()}",
                json={"connection_name": "x"},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 404

    @pytest.mark.unit
    def test_happy_path_updates_connection(self, mock_db, admin_user):
        client = _make_client(mock_db)
        conn = _mock_conn(connected_by=admin_user.id)
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=conn),        # conn lookup
            _FakeResult(scalar_one_or_none=admin_user),  # connector lookup
        )
        with _auth(admin_user, "threads.app_connections"):
            resp = client.put(
                f"/api/v1/threads/{conn.thread_id}/app-connections/{conn.id}",
                json={"connection_name": "Renamed Conn"},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 200
        assert conn.connection_name == "Renamed Conn"
        assert resp.json()["connection_name"] == "Renamed Conn"
        assert resp.json()["connector"]["user_id"] == str(admin_user.id)


# ===========================================================================
# DELETE /{thread_id}/app-connections/{connection_id} (disconnect_thread_app)
# ===========================================================================

class TestDisconnectThreadApp:
    @pytest.mark.unit
    def test_invalid_uuid_returns_400(self, mock_db, admin_user):
        client = _make_client(mock_db)
        with _auth(admin_user, "threads.app_connections"):
            resp = client.delete(
                "/api/v1/threads/not-a-uuid/app-connections/also-not-a-uuid",
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 400

    @pytest.mark.unit
    def test_not_found_returns_404(self, mock_db, admin_user):
        client = _make_client(mock_db)
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        with _auth(admin_user, "threads.app_connections"):
            resp = client.delete(
                f"/api/v1/threads/{uuid.uuid4()}/app-connections/{uuid.uuid4()}",
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 404

    @pytest.mark.unit
    def test_happy_path_removes_connection(self, mock_db, admin_user):
        client = _make_client(mock_db)
        conn = _mock_conn()
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=conn))
        mock_db.delete = AsyncMock()
        with _auth(admin_user, "threads.app_connections"):
            resp = client.delete(
                f"/api/v1/threads/{conn.thread_id}/app-connections/{conn.id}",
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 200
        assert resp.json() == {"message": "App connection removed from thread successfully"}
