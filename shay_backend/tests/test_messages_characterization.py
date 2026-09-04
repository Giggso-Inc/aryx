"""
Golden-master / characterization tests for app/routes/messages.py.

Purpose: messages.py is 2,513 lines with 15 endpoints and had ZERO test
coverage. It is about to be split into a package (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5). Before the split,
we capture the CURRENT observable behavior of every endpoint so the split
can be verified to change nothing.

These are characterization tests, not "correctness" tests: assertions match
what the code actually does today, bugs included.

Pattern follows tests/test_datasources_characterization.py and
tests/test_channels_characterization.py exactly:
- FastAPI TestClient with `app.include_router(router, prefix=...)`.
- `app.dependency_overrides[get_db] = lambda: mock_db`.
- MagicMock/AsyncMock for services; no real DB, no real HTTP.
- Background tasks (trigger_ai_processing, process_mention_notifications)
  are patched to no-ops: they run synchronously inside TestClient's request
  cycle and would otherwise try to open a real DB session
  (AsyncSessionLocal) against a database that doesn't exist in this test
  environment. Real code fails open on such errors (broad try/except), but
  patching keeps these tests fast and deterministic instead of relying on a
  swallowed connection-refused error.

Do not modify app/routes/messages.py from this file's tests.
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
    from app.routes.messages import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/messages")
    app.dependency_overrides[get_db] = lambda: mock_db
    return TestClient(app, raise_server_exceptions=False)


AUTH_HEADERS = {"Authorization": "Bearer test-token"}


def _auth(user, module):
    """Patch get_current_user_required on the specific submodule that owns
    the endpoint under test. Each submodule in app/routes/messages/ imports
    get_current_user_required itself, so patching the package (
    app.routes.messages.get_current_user_required) would NOT affect the
    submodule's own bound reference — this is the split's "CRITICAL GOTCHA"
    from the compliance plan: patch the exact module path, not the
    re-exporting package.
    """
    return patch(f"app.routes.messages.{module}.get_current_user_required", new=AsyncMock(return_value=user))


def _no_background():
    """Patch the two background-task entry points so create_message doesn't
    try to open a real DB session mid-test. Both are only ever called from
    messages_create.create_message."""
    return (
        patch("app.routes.messages.messages_create.trigger_ai_processing", new=AsyncMock()),
        patch("app.routes.messages.messages_create.process_mention_notifications", new=AsyncMock()),
    )


class _FakeResult:
    def __init__(self, scalar_one_or_none=None, all_=None, scalar_val=None, first_=None, rows=None, fetchall_=None):
        self._son = scalar_one_or_none
        self._all = all_ if all_ is not None else []
        self._scalar_val = scalar_val
        self._first = first_
        self._rows = rows if rows is not None else []
        self._fetchall = fetchall_ if fetchall_ is not None else []

    def scalar_one_or_none(self):
        return self._son

    def scalars(self):
        m = MagicMock()
        m.all = MagicMock(return_value=self._all)
        m.first = MagicMock(return_value=self._all[0] if self._all else None)
        return m

    def scalar(self):
        return self._scalar_val

    def first(self):
        return self._first

    def fetchall(self):
        return self._fetchall

    def all(self):
        return self._rows if self._rows else self._all

    def __iter__(self):
        return iter(self._rows)


def _exec_seq(*results):
    return AsyncMock(side_effect=list(results))


def _simulate_refresh(obj):
    """Fills in Column defaults a real DB applies on INSERT that our no-op
    mock_db.refresh() would otherwise leave as None (is_active, is_archived,
    message_count, is_ai_processed, is_visible, is_pinned)."""
    defaults = {
        "is_active": True,
        "is_archived": False,
        "message_count": 0,
        "is_ai_processed": False,
        "is_visible": True,
        "is_pinned": False,
        "ai_enabled": True,
    }
    for key, val in defaults.items():
        if getattr(obj, key, "unset") is None:
            setattr(obj, key, val)
    now = datetime.utcnow()
    if getattr(obj, "created_at", None) is None:
        obj.created_at = now
    if getattr(obj, "updated_at", None) is None:
        obj.updated_at = now


def _uid():
    return uuid.uuid4()


def _mock_channel(**overrides):
    ch = MagicMock()
    ch.id = _uid()
    ch.workspace_id = _uid()
    ch.company_id = "company-001"
    ch.ai_enabled = False  # default off so create_message doesn't schedule trigger_ai_processing
    ch.message_count = 0
    ch.last_message_at = None
    ch.channel_type = None
    ch.is_accessible_by_user = MagicMock(return_value=True)
    for k, v in overrides.items():
        setattr(ch, k, v)
    return ch


def _mock_thread(**overrides):
    th = MagicMock()
    th.id = _uid()
    th.title = "General"
    th.description = None
    th.channel_id = _uid()
    th.is_active = True
    th.is_archived = False
    th.message_count = 0
    th.last_message_at = None
    th.ai_enabled = False
    th.ai_summary = None
    th.first_message_id = None
    th.created_at = datetime.utcnow()
    th.updated_at = datetime.utcnow()
    for k, v in overrides.items():
        setattr(th, k, v)
    return th


def _mock_message(**overrides):
    m = MagicMock()
    m.id = _uid()
    m.content = "hello"
    m.message_type = "user"
    m.thread_id = _uid()
    m.user_id = "user-admin-001"
    m.query_id = None
    m.is_ai_processed = False
    m.ai_provider = None
    m.ai_model = None
    m.ai_processing_time = None
    m.is_visible = True
    m.is_pinned = False
    m.sequence_number = 1
    m.attachment_ids = None
    m.citations = None
    m.usage_metrics = None
    m.created_at = datetime.utcnow()
    m.updated_at = datetime.utcnow()
    for k, v in overrides.items():
        setattr(m, k, v)
    return m


def _mock_user_row(**overrides):
    u = MagicMock()
    u.id = "user-admin-001"
    u.email_id = "admin@example.com"
    u.name = "Admin User"
    u.role = "admin"
    u.avatar_url = None
    for k, v in overrides.items():
        setattr(u, k, v)
    return u


# ===========================================================================
# POST /threads — create_thread
# ===========================================================================

class TestCreateThread:
    def test_channel_not_found_404(self, mock_db, admin_user):
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        client = _make_client(mock_db)
        with _auth(admin_user, "threads_create"):
            resp = client.post(
                "/api/v1/messages/threads",
                json={"channel_id": str(_uid()), "title": "hi"},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 404

    def test_access_denied_403(self, mock_db, admin_user):
        channel = _mock_channel()
        channel.is_accessible_by_user = MagicMock(return_value=False)
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=channel))
        client = _make_client(mock_db)
        with _auth(admin_user, "threads_create"):
            resp = client.post(
                "/api/v1/messages/threads",
                json={"channel_id": str(channel.id), "title": "hi"},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 403

    def test_happy_path(self, mock_db, admin_user):
        channel = _mock_channel(ai_enabled=True)
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=channel))
        mock_db.refresh = AsyncMock(side_effect=_simulate_refresh)
        client = _make_client(mock_db)
        with _auth(admin_user, "threads_create"), patch("app.routes.messages.threads_create.audit_log_write", new=AsyncMock()):
            resp = client.post(
                "/api/v1/messages/threads",
                json={"channel_id": str(channel.id), "title": "hi"},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["title"] == "hi"
        assert body["ai_enabled"] is True  # inherited from channel


# ===========================================================================
# POST /threads/by-phone — get_or_create_thread_by_phone
# ===========================================================================

class TestGetOrCreateThreadByPhone:
    def test_invalid_channel_id_400(self, mock_db, admin_user):
        client = _make_client(mock_db)
        with _auth(admin_user, "threads_create"):
            resp = client.post(
                "/api/v1/messages/threads/by-phone",
                json={"phone_number": "+15551234567", "channel_id": "not-a-uuid"},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 400

    def test_channel_not_found_404(self, mock_db, admin_user):
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        client = _make_client(mock_db)
        with _auth(admin_user, "threads_create"):
            resp = client.post(
                "/api/v1/messages/threads/by-phone",
                json={"phone_number": "+15551234567", "channel_id": str(_uid())},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 404

    def test_existing_thread_returned(self, mock_db, admin_user):
        channel = _mock_channel()
        thread = _mock_thread(title="+15551234567")
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=channel),
            _FakeResult(scalar_one_or_none=thread),
        )
        client = _make_client(mock_db)
        with _auth(admin_user, "threads_create"):
            resp = client.post(
                "/api/v1/messages/threads/by-phone",
                json={"phone_number": "+15551234567", "channel_id": str(channel.id)},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["is_new"] is False
        assert body["thread_id"] == str(thread.id)

    def test_new_thread_created(self, mock_db, admin_user):
        channel = _mock_channel()
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=channel),
            _FakeResult(scalar_one_or_none=None),
        )
        mock_db.refresh = AsyncMock(side_effect=_simulate_refresh)
        client = _make_client(mock_db)
        with _auth(admin_user, "threads_create"), patch("app.routes.messages.threads_create.audit_log_write", new=AsyncMock()):
            resp = client.post(
                "/api/v1/messages/threads/by-phone",
                json={"phone_number": "+15551234567", "channel_id": str(channel.id)},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 200
        assert resp.json()["is_new"] is True


# ===========================================================================
# GET /threads — list_threads
# ===========================================================================

class TestListThreads:
    def test_missing_channel_id_422(self, mock_db, admin_user):
        client = _make_client(mock_db)
        with _auth(admin_user, "threads_list"):
            resp = client.get("/api/v1/messages/threads", headers=AUTH_HEADERS)
        assert resp.status_code == 422

    def test_channel_not_found_404(self, mock_db, admin_user):
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        client = _make_client(mock_db)
        with _auth(admin_user, "threads_list"):
            resp = client.get(f"/api/v1/messages/threads?channel_id={_uid()}", headers=AUTH_HEADERS)
        assert resp.status_code == 404

    def test_happy_path_empty(self, mock_db, admin_user):
        channel = _mock_channel()
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=channel),
            _FakeResult(all_=[]),
            _FakeResult(scalar_val=0),
        )
        client = _make_client(mock_db)
        with _auth(admin_user, "threads_list"):
            resp = client.get(f"/api/v1/messages/threads?channel_id={channel.id}", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        assert resp.json() == {"threads": [], "total": 0, "page": 1, "size": 10}

    def test_happy_path_with_thread(self, mock_db, admin_user):
        channel = _mock_channel()
        thread = _mock_thread(channel_id=channel.id)
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=channel),
            _FakeResult(all_=[thread]),
            _FakeResult(scalar_val=1),
            _FakeResult(scalar_one_or_none=None),  # first_message lookup
        )
        client = _make_client(mock_db)
        with _auth(admin_user, "threads_list"):
            resp = client.get(f"/api/v1/messages/threads?channel_id={channel.id}", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["threads"][0]["id"] == str(thread.id)
        assert body["threads"][0]["first_message_id"] is None


# ===========================================================================
# GET /threads/{thread_id} — get_thread_details
# ===========================================================================

class TestGetThreadDetails:
    def test_thread_not_found_404(self, mock_db, admin_user):
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        client = _make_client(mock_db)
        with _auth(admin_user, "threads_list"):
            resp = client.get(f"/api/v1/messages/threads/{_uid()}", headers=AUTH_HEADERS)
        assert resp.status_code == 404

    def test_happy_path(self, mock_db, admin_user):
        channel = _mock_channel()
        thread = _mock_thread(channel_id=channel.id)
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=thread),
            _FakeResult(scalar_one_or_none=channel),
            _FakeResult(scalar_one_or_none=None),
        )
        client = _make_client(mock_db)
        with _auth(admin_user, "threads_list"):
            resp = client.get(f"/api/v1/messages/threads/{thread.id}", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        assert resp.json()["id"] == str(thread.id)


# ===========================================================================
# POST / — create_message
# ===========================================================================

class TestCreateMessage:
    def _payload(self, thread_id, **overrides):
        payload = {"content": "hello world", "thread_id": str(thread_id)}
        payload.update(overrides)
        return payload

    def test_thread_not_found_404(self, mock_db, admin_user):
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        client = _make_client(mock_db)
        with _auth(admin_user, "messages_create"):
            resp = client.post("/api/v1/messages/", json=self._payload(_uid()), headers=AUTH_HEADERS)
        assert resp.status_code == 404

    def test_happy_path_user_message(self, mock_db, admin_user):
        thread = _mock_thread()
        channel = _mock_channel(id=thread.channel_id)
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=thread),
            _FakeResult(scalar_one_or_none=channel),
            _FakeResult(scalar_val=0),  # max sequence_number
            _FakeResult(scalar_one_or_none=None),  # user lookup for user_details
        )
        mock_db.refresh = AsyncMock(side_effect=_simulate_refresh)
        client = _make_client(mock_db)
        p1, p2 = _no_background()
        with _auth(admin_user, "messages_create"), patch("app.routes.messages.messages_create.audit_log_write", new=AsyncMock()), \
                patch("app.routes.messages.messages_create.link_shortener_service.shorten", new=AsyncMock(return_value="https://short.link/x")), \
                p1, p2:
            resp = client.post("/api/v1/messages/", json=self._payload(thread.id), headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["content"] == "hello world"
        assert body["sequence_number"] == 1

    def test_system_message_missing_query_id_400(self, mock_db, admin_user):
        thread = _mock_thread()
        channel = _mock_channel(id=thread.channel_id)
        system_user = _mock_user_row(id="system-user-001")
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=thread),
            _FakeResult(scalar_one_or_none=channel),
            _FakeResult(scalar_val=0),
            _FakeResult(scalar_one_or_none=system_user),  # get_or_create_system_user lookup
        )
        client = _make_client(mock_db)
        with _auth(admin_user, "messages_create"):
            resp = client.post(
                "/api/v1/messages/",
                json=self._payload(thread.id, message_type="system"),
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 400
        assert "query_id is required" in resp.json()["detail"]


# ===========================================================================
# GET /{thread_id} — get_thread_messages
# ===========================================================================

class TestGetThreadMessages:
    def test_thread_not_found_404(self, mock_db, admin_user):
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        client = _make_client(mock_db)
        with _auth(admin_user, "messages_read"):
            resp = client.get(f"/api/v1/messages/{_uid()}", headers=AUTH_HEADERS)
        assert resp.status_code == 404

    def test_happy_path_empty(self, mock_db, admin_user):
        thread = _mock_thread()
        channel = _mock_channel(id=thread.channel_id)
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=thread),
            _FakeResult(scalar_one_or_none=channel),
            _FakeResult(all_=[]),
            _FakeResult(scalar_val=0),
        )
        client = _make_client(mock_db)
        with _auth(admin_user, "messages_read"):
            resp = client.get(f"/api/v1/messages/{thread.id}", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        assert resp.json() == {"messages": [], "total": 0, "page": 1, "size": 50}


# ===========================================================================
# POST /message/{message_id}/hide — hide_thread_messages
# ===========================================================================

class TestHideThreadMessages:
    def test_invalid_message_id_400(self, mock_db, admin_user):
        client = _make_client(mock_db)
        with _auth(admin_user, "messages_hide"):
            resp = client.post("/api/v1/messages/message/not-a-uuid/hide", headers=AUTH_HEADERS)
        assert resp.status_code == 400

    def test_message_not_found_404(self, mock_db, admin_user):
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        client = _make_client(mock_db)
        with _auth(admin_user, "messages_hide"):
            resp = client.post(f"/api/v1/messages/message/{_uid()}/hide", headers=AUTH_HEADERS)
        assert resp.status_code == 404

    def test_happy_path(self, mock_db, admin_user):
        thread = _mock_thread()
        channel = _mock_channel(id=thread.channel_id)
        message = _mock_message(thread_id=thread.id)
        mock_db.execute = AsyncMock(side_effect=[
            _FakeResult(scalar_one_or_none=message),
            _FakeResult(scalar_one_or_none=thread),
            _FakeResult(scalar_one_or_none=channel),
            MagicMock(rowcount=1),
        ])
        client = _make_client(mock_db)
        with _auth(admin_user, "messages_hide"), patch("app.routes.messages.messages_hide.audit_log_write", new=AsyncMock()):
            resp = client.post(f"/api/v1/messages/message/{message.id}/hide", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["hidden_count"] == 1


# ===========================================================================
# GET /message/{message_id} — get_message_details
# ===========================================================================

class TestGetMessageDetails:
    def test_message_not_found_404(self, mock_db, admin_user):
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        client = _make_client(mock_db)
        with _auth(admin_user, "messages_read"):
            resp = client.get(f"/api/v1/messages/message/{_uid()}", headers=AUTH_HEADERS)
        assert resp.status_code == 404

    def test_happy_path(self, mock_db, admin_user):
        thread = _mock_thread()
        channel = _mock_channel(id=thread.channel_id)
        message = _mock_message(thread_id=thread.id, user_id=None)
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=message),
            _FakeResult(scalar_one_or_none=thread),
            _FakeResult(scalar_one_or_none=channel),
        )
        client = _make_client(mock_db)
        with _auth(admin_user, "messages_read"):
            resp = client.get(f"/api/v1/messages/message/{message.id}", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        assert resp.json()["id"] == str(message.id)


# ===========================================================================
# POST /update — update_message
# ===========================================================================

class TestUpdateMessage:
    def _payload(self, message_id, thread_id, **overrides):
        payload = {"message_id": str(message_id), "thread_id": str(thread_id), "content": "edited"}
        payload.update(overrides)
        return payload

    def test_invalid_id_format_400(self, mock_db, admin_user):
        client = _make_client(mock_db)
        with _auth(admin_user, "messages_update"):
            resp = client.post(
                "/api/v1/messages/update",
                json=self._payload("not-a-uuid", _uid()),
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 400

    def test_message_not_found_404(self, mock_db, admin_user):
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        client = _make_client(mock_db)
        with _auth(admin_user, "messages_update"):
            resp = client.post(
                "/api/v1/messages/update",
                json=self._payload(_uid(), _uid()),
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 404

    def test_wrong_thread_400(self, mock_db, admin_user):
        message = _mock_message()
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=message))
        client = _make_client(mock_db)
        with _auth(admin_user, "messages_update"):
            resp = client.post(
                "/api/v1/messages/update",
                json=self._payload(message.id, _uid()),  # different thread_id
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 400
        assert "does not belong" in resp.json()["detail"]

    def test_not_own_message_403(self, mock_db, regular_user):
        thread = _mock_thread()
        message = _mock_message(thread_id=thread.id, user_id="someone-else")
        channel = _mock_channel(id=thread.channel_id)
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=message),
            _FakeResult(scalar_one_or_none=thread),
            _FakeResult(scalar_one_or_none=channel),
        )
        client = _make_client(mock_db)
        with _auth(regular_user, "messages_update"):
            resp = client.post(
                "/api/v1/messages/update",
                json=self._payload(message.id, thread.id),
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 403

    def test_happy_path(self, mock_db, admin_user):
        thread = _mock_thread()
        message = _mock_message(thread_id=thread.id, user_id=admin_user.id, attachment_ids=None)
        channel = _mock_channel(id=thread.channel_id)
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=message),
            _FakeResult(scalar_one_or_none=thread),
            _FakeResult(scalar_one_or_none=channel),
            _FakeResult(scalar_one_or_none=None),  # user lookup for response
        )
        client = _make_client(mock_db)
        with _auth(admin_user, "messages_update"), patch("app.routes.messages.messages_update.audit_log_write", new=AsyncMock()):
            resp = client.post(
                "/api/v1/messages/update",
                json=self._payload(message.id, thread.id, content="updated content"),
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 200
        assert resp.json()["content"] == "updated content"
        assert message.content == "updated content"


# ===========================================================================
# DELETE /delete — delete_message
# ===========================================================================

class TestDeleteMessage:
    def _payload(self, message_id, thread_id):
        return {"message_id": str(message_id), "thread_id": str(thread_id)}

    def test_invalid_id_format_400(self, mock_db, admin_user):
        client = _make_client(mock_db)
        with _auth(admin_user, "messages_delete"):
            resp = client.request(
                "DELETE", "/api/v1/messages/delete",
                json=self._payload("not-a-uuid", _uid()),
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 400

    def test_message_not_found_404(self, mock_db, admin_user):
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        client = _make_client(mock_db)
        with _auth(admin_user, "messages_delete"):
            resp = client.request(
                "DELETE", "/api/v1/messages/delete",
                json=self._payload(_uid(), _uid()),
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 404

    def test_not_own_message_403(self, mock_db, regular_user):
        thread = _mock_thread()
        message = _mock_message(thread_id=thread.id, user_id="someone-else")
        channel = _mock_channel(id=thread.channel_id)
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=message),
            _FakeResult(scalar_one_or_none=thread),
            _FakeResult(scalar_one_or_none=channel),
        )
        client = _make_client(mock_db)
        with _auth(regular_user, "messages_delete"):
            resp = client.request(
                "DELETE", "/api/v1/messages/delete",
                json=self._payload(message.id, thread.id),
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 403

    def test_happy_path(self, mock_db, admin_user):
        thread = _mock_thread(message_count=1)
        message = _mock_message(thread_id=thread.id, user_id=admin_user.id, attachment_ids=None)
        channel = _mock_channel(id=thread.channel_id, message_count=1)
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=message),
            _FakeResult(scalar_one_or_none=thread),
            _FakeResult(scalar_one_or_none=channel),
            _FakeResult(all_=[]),  # dependent messages (query_id == this message)
            _FakeResult(all_=[]),  # AI responses for main message
            _FakeResult(scalar_one_or_none=None),  # last message in thread
            _FakeResult(scalar_one_or_none=None),  # last message in channel
        )
        client = _make_client(mock_db)
        with _auth(admin_user, "messages_delete"), patch("app.routes.messages.messages_delete.audit_log_write", new=AsyncMock()):
            resp = client.request(
                "DELETE", "/api/v1/messages/delete",
                json=self._payload(message.id, thread.id),
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["message"] == "Message deleted successfully"
        assert body["deleted_query_id_messages"] == 0
        assert thread.message_count == 0
        assert channel.message_count == 0


# ===========================================================================
# GET /threads/{thread_id}/summary — get_thread_summary
# ===========================================================================

class TestGetThreadSummary:
    def test_thread_not_found_404(self, mock_db, admin_user):
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        client = _make_client(mock_db)
        with _auth(admin_user, "threads_manage"):
            resp = client.get(f"/api/v1/messages/threads/{_uid()}/summary", headers=AUTH_HEADERS)
        assert resp.status_code == 404

    def test_happy_path(self, mock_db, admin_user):
        thread = _mock_thread()
        channel = _mock_channel(id=thread.channel_id)
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=thread),
            _FakeResult(scalar_one_or_none=channel),
        )
        client = _make_client(mock_db)
        with _auth(admin_user, "threads_manage"):
            resp = client.get(f"/api/v1/messages/threads/{thread.id}/summary", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        assert resp.json()["thread_id"] == str(thread.id)


# ===========================================================================
# PUT /threads/{thread_id} — update_thread
# ===========================================================================

class TestUpdateThread:
    def test_thread_not_found_404(self, mock_db, admin_user):
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        client = _make_client(mock_db)
        with _auth(admin_user, "threads_manage"):
            resp = client.put(f"/api/v1/messages/threads/{_uid()}", json={"title": "new"}, headers=AUTH_HEADERS)
        assert resp.status_code == 404

    def test_access_denied_403(self, mock_db, admin_user):
        thread = _mock_thread()
        channel = _mock_channel(id=thread.channel_id)
        channel.is_accessible_by_user = MagicMock(return_value=False)
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=thread),
            _FakeResult(scalar_one_or_none=channel),
        )
        client = _make_client(mock_db)
        with _auth(admin_user, "threads_manage"):
            resp = client.put(f"/api/v1/messages/threads/{thread.id}", json={"title": "new"}, headers=AUTH_HEADERS)
        assert resp.status_code == 403

    def test_happy_path(self, mock_db, admin_user):
        thread = _mock_thread(title="old")
        channel = _mock_channel(id=thread.channel_id)
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=thread),
            _FakeResult(scalar_one_or_none=channel),
        )
        client = _make_client(mock_db)
        with _auth(admin_user, "threads_manage"), patch("app.routes.messages.threads_manage.audit_log_write", new=AsyncMock()):
            resp = client.put(f"/api/v1/messages/threads/{thread.id}", json={"title": "new title"}, headers=AUTH_HEADERS)
        assert resp.status_code == 200
        assert resp.json()["title"] == "new title"
        assert thread.title == "new title"


# ===========================================================================
# POST /threads/move — move_thread
# ===========================================================================

class TestMoveThread:
    def _payload(self, thread_id, new_channel_id):
        return {"thread_id": str(thread_id), "new_channel_id": str(new_channel_id)}

    def test_thread_not_found_404(self, mock_db, admin_user):
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        client = _make_client(mock_db)
        with _auth(admin_user, "threads_move"):
            resp = client.post("/api/v1/messages/threads/move", json=self._payload(_uid(), _uid()), headers=AUTH_HEADERS)
        assert resp.status_code == 404

    def test_same_channel_400(self, mock_db, admin_user):
        ch_id = _uid()
        thread = _mock_thread(channel_id=ch_id)
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=thread))
        client = _make_client(mock_db)
        with _auth(admin_user, "threads_move"):
            resp = client.post("/api/v1/messages/threads/move", json=self._payload(thread.id, ch_id), headers=AUTH_HEADERS)
        assert resp.status_code == 400
        assert "already in this channel" in resp.json()["detail"]

    def test_non_message_channel_type_400(self, mock_db, admin_user):
        thread = _mock_thread()
        src = _mock_channel(id=thread.channel_id, channel_type="email", workspace_id="ws-1")
        dest = _mock_channel(channel_type="message", workspace_id="ws-1")
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=thread),
            _FakeResult(scalar_one_or_none=src),
            _FakeResult(scalar_one_or_none=dest),
        )
        client = _make_client(mock_db)
        with _auth(admin_user, "threads_move"):
            resp = client.post("/api/v1/messages/threads/move", json=self._payload(thread.id, dest.id), headers=AUTH_HEADERS)
        assert resp.status_code == 400
        assert "regular (message-type)" in resp.json()["detail"]

    def test_cross_workspace_400(self, mock_db, admin_user):
        thread = _mock_thread()
        src = _mock_channel(id=thread.channel_id, channel_type="message", workspace_id="ws-1")
        dest = _mock_channel(channel_type="message", workspace_id="ws-2")
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=thread),
            _FakeResult(scalar_one_or_none=src),
            _FakeResult(scalar_one_or_none=dest),
        )
        client = _make_client(mock_db)
        with _auth(admin_user, "threads_move"):
            resp = client.post("/api/v1/messages/threads/move", json=self._payload(thread.id, dest.id), headers=AUTH_HEADERS)
        assert resp.status_code == 400
        assert "across workspaces" in resp.json()["detail"]

    def test_inactive_thread_400(self, mock_db, admin_user):
        thread = _mock_thread(is_active=False)
        src = _mock_channel(id=thread.channel_id, channel_type="message", workspace_id="ws-1")
        dest = _mock_channel(channel_type="message", workspace_id="ws-1")
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=thread),
            _FakeResult(scalar_one_or_none=src),
            _FakeResult(scalar_one_or_none=dest),
        )
        client = _make_client(mock_db)
        with _auth(admin_user, "threads_move"):
            resp = client.post("/api/v1/messages/threads/move", json=self._payload(thread.id, dest.id), headers=AUTH_HEADERS)
        assert resp.status_code == 400
        assert "active, non-archived" in resp.json()["detail"]

    def test_happy_path(self, mock_db, admin_user):
        thread = _mock_thread(is_active=True, is_archived=False)
        src = _mock_channel(id=thread.channel_id, channel_type="message", workspace_id="ws-1")
        dest = _mock_channel(channel_type="message", workspace_id="ws-1")
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=thread),
            _FakeResult(scalar_one_or_none=src),
            _FakeResult(scalar_one_or_none=dest),
            MagicMock(rowcount=1),  # update Thread
            MagicMock(rowcount=2),  # update Message
            MagicMock(rowcount=0),  # update EmailAttachment
            MagicMock(rowcount=0),  # update Attachment
            MagicMock(rowcount=0),  # update ShortenedUrl
        )
        client = _make_client(mock_db)
        with _auth(admin_user, "threads_move"), patch("app.routes.messages.threads_move.audit_log_write", new=AsyncMock()):
            resp = client.post("/api/v1/messages/threads/move", json=self._payload(thread.id, dest.id), headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["updated_counts"]["gg_threads"] == 1
        assert body["updated_counts"]["gg_messages"] == 2
        assert body["updated_counts"]["gg_approvals"] == 0
        assert body["updated_counts"]["gg_tasks"] == 0


# ===========================================================================
# DELETE /threads/{thread_id} — delete_thread
# ===========================================================================

class TestDeleteThread:
    def test_thread_not_found_404(self, mock_db, admin_user):
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        client = _make_client(mock_db)
        with _auth(admin_user, "threads_delete"):
            resp = client.delete(f"/api/v1/messages/threads/{_uid()}", headers=AUTH_HEADERS)
        assert resp.status_code == 404

    def test_non_admin_403(self, mock_db, regular_user):
        thread = _mock_thread()
        channel = _mock_channel(id=thread.channel_id)
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=thread),
            _FakeResult(scalar_one_or_none=channel),
        )
        client = _make_client(mock_db)
        with _auth(regular_user, "threads_delete"):
            resp = client.delete(f"/api/v1/messages/threads/{thread.id}", headers=AUTH_HEADERS)
        assert resp.status_code == 403
        assert "administrators" in resp.json()["detail"]

    def test_happy_path_non_email_channel(self, mock_db, admin_user):
        thread = _mock_thread()
        channel = _mock_channel(id=thread.channel_id, channel_type="message")
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=thread),
            _FakeResult(scalar_one_or_none=channel),
            _FakeResult(scalar_val=0),  # message_count
            _FakeResult(all_=[]),       # messages to delete
            _FakeResult(scalar_one_or_none=None),  # fallback email AppAccount check
            _FakeResult(all_=[]),       # AI responses
        )
        client = _make_client(mock_db)
        with _auth(admin_user, "threads_delete"), patch("app.routes.messages.threads_delete.audit_log_write", new=AsyncMock()):
            resp = client.delete(f"/api/v1/messages/threads/{thread.id}", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["message"] == "Thread deleted successfully"
        assert body["deleted_messages"] == 0
        mock_db.commit.assert_awaited()


# ===========================================================================
# POST /ml-store — store_ml_messages
# ===========================================================================

class TestStoreMlMessages:
    def _payload(self, thread_id, **overrides):
        payload = {"prompt": "what is x?", "response": "x is y", "thread_id": str(thread_id)}
        payload.update(overrides)
        return payload

    def test_invalid_thread_id_returns_failed_status_200(self, mock_db, admin_user):
        client = _make_client(mock_db)
        with _auth(admin_user, "ml_store"):
            resp = client.post(
                "/api/v1/messages/ml-store",
                json=self._payload("not-a-uuid"),
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "failed"
        assert "Invalid thread_id" in resp.json()["message"]

    def test_thread_not_found_returns_failed_status_200(self, mock_db, admin_user):
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        client = _make_client(mock_db)
        with _auth(admin_user, "ml_store"):
            resp = client.post(
                "/api/v1/messages/ml-store",
                json=self._payload(_uid()),
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "failed"
        assert resp.json()["message"] == "Thread not found"

    def test_happy_path(self, mock_db, admin_user):
        thread = _mock_thread()
        channel = _mock_channel(id=thread.channel_id)
        system_user = _mock_user_row(id="system-user-001", role="system")
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=thread),
            _FakeResult(scalar_one_or_none=channel),
            _FakeResult(scalar_one_or_none=system_user),  # get_or_create_system_user
            _FakeResult(scalar_val=0),  # max sequence number
        )
        mock_db.refresh = AsyncMock(side_effect=_simulate_refresh)
        client = _make_client(mock_db)
        p1, p2 = _no_background()
        with _auth(admin_user, "ml_store"), patch("app.routes.messages.ml_store.audit_log_write", new=AsyncMock()), p1, p2:
            resp = client.post(
                "/api/v1/messages/ml-store",
                json=self._payload(thread.id),
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "success"
        assert len(body["data"]) == 2
        assert body["data"][0]["message_type"] == "user"
        assert body["data"][1]["message_type"] == "system"

    def test_exception_is_caught_and_reported_as_failed(self, mock_db, admin_user):
        """store_ml_messages wraps its entire body in try/except and always
        returns HTTP 200 with status='failed' on any exception (including a
        raw DB error), rather than propagating an HTTP error status."""
        mock_db.execute = AsyncMock(side_effect=RuntimeError("boom"))
        client = _make_client(mock_db)
        with _auth(admin_user, "ml_store"):
            resp = client.post(
                "/api/v1/messages/ml-store",
                json=self._payload(_uid()),
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "failed"
        assert "boom" in resp.json()["message"]
        mock_db.rollback.assert_awaited()
