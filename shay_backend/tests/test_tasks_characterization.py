"""
Golden-master / characterization tests for app/routes/tasks.py.

Purpose: this file (2,547 lines, 12 endpoints, zero prior test coverage) is
about to be split into a package (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2, following
the same methodology already applied to app/routes/datasources.py). Before
the split, we capture the CURRENT observable behavior of every endpoint so
the split can be verified to change nothing.

These are characterization tests, not "correctness" tests: assertions match
what the code actually does today, bugs included. Where the code has a
pre-existing defect (e.g. update_task/delete_task/assign_task/
update_task_status all read `task.channel_id` / `task.thread_id` for audit
logging even though the Task model has no such columns — those attributes
only "work" here because the mocked task is a MagicMock, not a real Task
row), the test documents current behavior rather than "fixing" it.

Pattern follows tests/test_datasources_characterization.py exactly:
- FastAPI TestClient with `app.include_router(router, prefix=...)`.
- `app.dependency_overrides[get_db] = lambda: mock_db`.
- MagicMock/AsyncMock for services; no real DB, no real HTTP.
- `_run()` + asyncio.run() instead of pytest-asyncio (no async plugin
  installed in this suite).
- `mock_db.execute` is driven by an ordered `side_effect` list of
  `_FakeResult` objects — one per `db.execute(...)` call the endpoint makes,
  in call order (verified by reading the endpoint source top to bottom).

Do not modify app/routes/tasks.py from this file's tests.
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
    from app.routes.tasks import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/tasks")
    app.dependency_overrides[get_db] = lambda: mock_db
    return TestClient(app, raise_server_exceptions=False)


AUTH_HEADERS = {"Authorization": "Bearer test-token"}


def _auth(user, module="tasks"):
    return patch(f"app.routes.{module}.get_current_user_required", new=AsyncMock(return_value=user))


class _FakeResult:
    """Mimics the subset of SQLAlchemy's async Result API these endpoints
    actually call: .scalar_one_or_none(), .scalars().all(), .scalar(),
    and plain .all() (used for id-only projection queries)."""

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
    ch.name = "general"
    ch.is_accessible_by_user = MagicMock(return_value=True)
    ch.message_count = 0
    for k, v in overrides.items():
        setattr(ch, k, v)
    return ch


def _mock_message(**overrides):
    msg = MagicMock()
    msg.id = uuid.uuid4()
    msg.channel_id = uuid.uuid4()
    msg.thread_id = uuid.uuid4()
    msg.workspace_id = uuid.uuid4()
    msg.sequence_number = 1
    msg.content = "hello"
    for k, v in overrides.items():
        setattr(msg, k, v)
    return msg


def _mock_task(**overrides):
    t = MagicMock()
    t.id = uuid.uuid4()
    t.title = "Do the thing"
    t.description = "desc"
    t.status = "Open"
    t.source = "manual"
    t.due_date = None
    t.priority = "Medium"
    t.tags = None
    t.task_metadata = None
    t.created_at = datetime(2026, 1, 1)
    t.updated_at = datetime(2026, 1, 1)
    t.completed_at = None
    t.assigned_to = None
    t.created_by = None
    t.message_id = None
    t.checklists = []
    t.is_overdue = False
    t.is_urgent = False
    for k, v in overrides.items():
        setattr(t, k, v)
    return t


def _simulate_task_refresh(obj, **_ignored):
    """create_task/create_thread_task build a real Task() ORM instance and rely on
    db.refresh() to pick up server-side column defaults (created_at/updated_at use
    func.current_timestamp()). Our mock_db.refresh() is a bare AsyncMock no-op, so
    without this the freshly-constructed object would still have these as None —
    which a real database would never do. Used as mock_db.refresh.side_effect."""
    now = datetime.utcnow()
    if getattr(obj, "created_at", None) is None:
        obj.created_at = now
    if getattr(obj, "updated_at", None) is None:
        obj.updated_at = now


def _mock_thread(**overrides):
    th = MagicMock()
    th.id = uuid.uuid4()
    th.title = "Thread title"
    th.channel_id = uuid.uuid4()
    for k, v in overrides.items():
        setattr(th, k, v)
    return th


def _mock_user(**overrides):
    u = MagicMock()
    u.id = uuid.uuid4()
    u.company_id = "company-001"
    u.name = "Some User"
    u.email_id = "user@example.com"
    u.role = "user"
    for k, v in overrides.items():
        setattr(u, k, v)
    return u


# ===========================================================================
# POST / (create_task)
# ===========================================================================

class TestCreateTask:
    @pytest.mark.unit
    def test_message_not_found_returns_404(self, mock_db, admin_user):
        client = _make_client(mock_db)
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        with _auth(admin_user, "tasks.create"):
            resp = client.post(
                "/api/v1/tasks/",
                json={"title": "T", "message_id": str(uuid.uuid4()), "assigned_to": str(uuid.uuid4())},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Message not found"

    @pytest.mark.unit
    def test_happy_path_creates_task_and_returns_response(self, mock_db, admin_user):
        client = _make_client(mock_db)
        message = _mock_message()
        workspace = MagicMock(id=message.workspace_id, company_id=admin_user.company_id)
        channel = _mock_channel(id=message.channel_id, company_id=admin_user.company_id)
        assigned_user = _mock_user(company_id=admin_user.company_id)
        channel_member = MagicMock()

        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=message),      # message_stmt
            _FakeResult(scalar_one_or_none=workspace),     # workspace_stmt
            _FakeResult(scalar_one_or_none=channel),       # channel_stmt
            _FakeResult(scalar_one_or_none=assigned_user), # assigned_user_stmt
            _FakeResult(scalar_one_or_none=channel_member),# channel_member_stmt
            _FakeResult(all_=[]),                          # thread_messages_stmt (no other messages)
        )
        mock_db.refresh = AsyncMock(side_effect=_simulate_task_refresh)

        with _auth(admin_user, "tasks.create"), \
             patch("app.routes.tasks.create.link_shortener_service.shorten", new=AsyncMock(return_value="#")), \
             patch("app.routes.tasks.create.process_task_assignment_notifications", new=AsyncMock()):
            resp = client.post(
                "/api/v1/tasks/",
                json={
                    "title": "New Task",
                    "message_id": str(message.id),
                    "assigned_to": str(assigned_user.id),
                },
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["title"] == "New Task"
        assert body["status"] == "Open"
        assert body["checklists"] == []
        # Note: the handler's hand-built response dict includes assigned_to,
        # created_by, and message_id, but TaskResponse (this route's response_model)
        # declares none of those fields, so FastAPI's response filtering drops them.
        assert "assigned_to" not in body
        assert "created_by" not in body
        assert "message_id" not in body


# ===========================================================================
# GET / (list_tasks)
# ===========================================================================

class TestListTasks:
    @pytest.mark.unit
    def test_no_channels_returns_empty_list(self, mock_db, admin_user):
        client = _make_client(mock_db)
        mock_db.execute = _exec_seq(_FakeResult())  # user_channels_query -> scalars().all() == []
        with _auth(admin_user, "tasks.list_tasks"):
            resp = client.get("/api/v1/tasks/", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body == {"tasks": [], "total": 0, "page": 1, "size": 10, "has_more": False}

    @pytest.mark.unit
    def test_current_behavior_500_when_user_has_channels(self, mock_db, admin_user):
        """Pre-existing defect: as soon as user_channel_ids is non-empty, the code
        builds `select(Message.id).where(Message.channel_id.in_(...))` — but the
        Message model (app/models/message.py) has no `channel_id` column (only
        Thread does). `Message.channel_id` raises AttributeError at query-build
        time, before any db.execute() call, so this endpoint 500s for literally
        any authenticated user who belongs to at least one active channel."""
        client = _make_client(mock_db)
        mock_db.execute = _exec_seq(_FakeResult(all_=[uuid.uuid4()]))  # user_channels_query
        with _auth(admin_user, "tasks.list_tasks"):
            resp = client.get("/api/v1/tasks/", headers=AUTH_HEADERS)
        assert resp.status_code == 500


# ===========================================================================
# GET /count (get_task_count)
# ===========================================================================

class TestGetTaskCount:
    @pytest.mark.unit
    def test_no_channels_returns_zero(self, mock_db, admin_user):
        client = _make_client(mock_db)
        mock_db.execute = _exec_seq(_FakeResult())
        with _auth(admin_user, "tasks.count"):
            resp = client.get("/api/v1/tasks/count", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        assert resp.json() == {"task_count": 0}

    @pytest.mark.unit
    def test_current_behavior_500_when_user_has_channels(self, mock_db, admin_user):
        """Same pre-existing `Message.channel_id` defect as list_tasks (see
        TestListTasks) — this endpoint's comment even says it "uses the same
        logic as list_tasks endpoint", inheriting the same crash."""
        client = _make_client(mock_db)
        mock_db.execute = _exec_seq(_FakeResult(all_=[uuid.uuid4()]))  # user_channels_query
        with _auth(admin_user, "tasks.count"):
            resp = client.get("/api/v1/tasks/count", headers=AUTH_HEADERS)
        assert resp.status_code == 500


# ===========================================================================
# GET /{task_id} (get_task)
# ===========================================================================

class TestGetTask:
    @pytest.mark.unit
    def test_not_found_returns_404(self, mock_db, admin_user):
        client = _make_client(mock_db)
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        with _auth(admin_user, "tasks.detail"):
            resp = client.get(f"/api/v1/tasks/{uuid.uuid4()}", headers=AUTH_HEADERS)
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Task not found"

    @pytest.mark.unit
    def test_happy_path_no_message_link(self, mock_db, admin_user):
        client = _make_client(mock_db)
        task = _mock_task()
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=task))
        with _auth(admin_user, "tasks.detail"):
            resp = client.get(f"/api/v1/tasks/{task.id}", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["title"] == "Do the thing"
        # Note: the handler computes `task_history` and does `response['task_history']
        # = task_history`, but the route's response_model is TaskResponse, which has
        # no task_history field — FastAPI's response filtering silently drops it.
        assert "task_history" not in body


# ===========================================================================
# PUT /{task_id} (update_task)
# ===========================================================================

class TestUpdateTask:
    @pytest.mark.unit
    def test_not_found_returns_404(self, mock_db, admin_user):
        client = _make_client(mock_db)
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        with _auth(admin_user, "tasks.update"):
            resp = client.put(f"/api/v1/tasks/{uuid.uuid4()}", json={"title": "x"}, headers=AUTH_HEADERS)
        assert resp.status_code == 404

    @pytest.mark.unit
    def test_happy_path_updates_title(self, mock_db, admin_user):
        client = _make_client(mock_db)
        task = _mock_task(message_id=None)
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=task))
        with _auth(admin_user, "tasks.update"):
            resp = client.put(
                f"/api/v1/tasks/{task.id}",
                json={"title": "Updated Title"},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 200
        assert task.title == "Updated Title"
        assert resp.json()["title"] == "Updated Title"


# ===========================================================================
# DELETE /{task_id} (delete_task)
# ===========================================================================

class TestDeleteTask:
    @pytest.mark.unit
    def test_not_found_returns_404(self, mock_db, admin_user):
        client = _make_client(mock_db)
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        with _auth(admin_user, "tasks.delete"):
            resp = client.delete(f"/api/v1/tasks/{uuid.uuid4()}", headers=AUTH_HEADERS)
        assert resp.status_code == 404

    @pytest.mark.unit
    def test_happy_path_deletes_task(self, mock_db, admin_user):
        client = _make_client(mock_db)
        task = _mock_task(created_by=admin_user.id, message_id=None)
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=task))
        mock_db.delete = AsyncMock()
        with _auth(admin_user, "tasks.delete"):
            resp = client.delete(f"/api/v1/tasks/{task.id}", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        assert resp.json() == {"message": "Task deleted successfully"}
        mock_db.delete.assert_awaited_once_with(task)


# ===========================================================================
# POST /{task_id}/assign (assign_task)
# ===========================================================================

class TestAssignTask:
    @pytest.mark.unit
    def test_not_found_returns_404(self, mock_db, admin_user):
        client = _make_client(mock_db)
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        with _auth(admin_user, "tasks.assign"):
            resp = client.post(
                f"/api/v1/tasks/{uuid.uuid4()}/assign",
                json={"assigned_to": str(uuid.uuid4())},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 404

    @pytest.mark.unit
    def test_happy_path_reassigns_task(self, mock_db, admin_user):
        client = _make_client(mock_db)
        task = _mock_task(message_id=None, assigned_to=None)
        new_assignee = _mock_user(company_id=admin_user.company_id)

        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=task),          # task_stmt
            _FakeResult(scalar_one_or_none=new_assignee),  # validate assigned user
            _FakeResult(scalar_one_or_none=new_assignee),  # load_task_details' assignee lookup
        )
        with _auth(admin_user, "tasks.assign"):
            resp = client.post(
                f"/api/v1/tasks/{task.id}/assign",
                json={"assigned_to": str(new_assignee.id)},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 200
        # assignment_data.assigned_to is typed Union[str, UUID]; Pydantic matches the
        # first alternative that validates (str), so the value assigned onto the task
        # stays a string rather than being coerced to a UUID.
        assert task.assigned_to == str(new_assignee.id)
        assert resp.json()["assigned_user"]["id"] == str(new_assignee.id)


# ===========================================================================
# POST /{task_id}/status (update_task_status)
# ===========================================================================

class TestUpdateTaskStatus:
    @pytest.mark.unit
    def test_not_found_returns_404(self, mock_db, admin_user):
        client = _make_client(mock_db)
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        with _auth(admin_user, "tasks.status_update"):
            resp = client.post(
                f"/api/v1/tasks/{uuid.uuid4()}/status",
                json={"status": "Close"},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 404

    @pytest.mark.unit
    def test_happy_path_closes_task(self, mock_db, admin_user):
        client = _make_client(mock_db)
        task = _mock_task(created_by=admin_user.id, message_id=None, status="Open", task_metadata=None)
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=task))
        with _auth(admin_user, "tasks.status_update"):
            resp = client.post(
                f"/api/v1/tasks/{task.id}/status",
                json={"status": "Close"},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 200
        assert task.status == "Close"
        assert resp.json()["status"] == "Close"
        # Pre-existing defect: the handler does `task.status = status_data.status`
        # *before* checking `if status_data.status == 'Close' and task.status !=
        # 'Close'` — by then task.status already equals 'Close', so this branch's
        # condition is always False and completed_at is never set on close via
        # this endpoint (unlike update_task's PUT handler, which checks the old
        # status first).
        assert resp.json()["completed_at"] is None


# ===========================================================================
# GET /stats/overview (get_task_stats)
# ===========================================================================

class TestGetTaskStats:
    @pytest.mark.unit
    def test_current_behavior_500_no_accessible_workspaces(self, mock_db, admin_user):
        """Pre-existing defect: every early-return branch in this endpoint builds
        `TaskStats(total_tasks=0, open_tasks=0, in_progress_tasks=0, on_hold_tasks=0,
        closed_tasks=0, urgent_tasks=0)` — omitting the required `overdue_tasks`
        field entirely. TaskStats.overdue_tasks has no default, so response-model
        validation fails and FastAPI returns 500, even on this "no data" path."""
        client = _make_client(mock_db)
        mock_db.execute = _exec_seq(_FakeResult(all_=[]))
        with _auth(admin_user, "tasks.stats"):
            resp = client.get("/api/v1/tasks/stats/overview", headers=AUTH_HEADERS)
        assert resp.status_code == 500

    @pytest.mark.unit
    def test_current_behavior_500_when_channels_have_messages(self, mock_db, admin_user):
        """Pre-existing defect: the main path builds `select(Message.id).where(
        Message.channel_id.in_(...))` — same missing-column AttributeError as
        list_tasks/get_task_count (Message has no channel_id column)."""
        client = _make_client(mock_db)
        mock_db.execute = _exec_seq(
            _FakeResult(all_=[uuid.uuid4()]),  # workspace_query
            _FakeResult(all_=[uuid.uuid4()]),  # channels_query
        )
        with _auth(admin_user, "tasks.stats"):
            resp = client.get("/api/v1/tasks/stats/overview", headers=AUTH_HEADERS)
        assert resp.status_code == 500


# ===========================================================================
# GET /thread/{thread_id} (get_thread_task)
# ===========================================================================

class TestGetThreadTask:
    @pytest.mark.unit
    def test_thread_not_found_returns_404(self, mock_db, admin_user):
        client = _make_client(mock_db)
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        with _auth(admin_user, "tasks.thread_detail"):
            resp = client.get(f"/api/v1/tasks/thread/{uuid.uuid4()}", headers=AUTH_HEADERS)
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Thread not found"

    @pytest.mark.unit
    def test_happy_path_returns_latest_task(self, mock_db, admin_user):
        client = _make_client(mock_db)
        thread = _mock_thread()
        channel = _mock_channel(id=thread.channel_id)
        task = _mock_task()

        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=thread),
            _FakeResult(scalar_one_or_none=channel),
            _FakeResult(all_=[(uuid.uuid4(),)]),
            _FakeResult(scalar_one_or_none=task),
        )
        with _auth(admin_user, "tasks.thread_detail"):
            resp = client.get(f"/api/v1/tasks/thread/{thread.id}", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        assert resp.json()["title"] == "Do the thing"


# ===========================================================================
# GET /thread/{thread_id}/status (get_thread_task_status)
# ===========================================================================

class TestGetThreadTaskStatus:
    @pytest.mark.unit
    def test_thread_not_found_returns_404(self, mock_db, admin_user):
        client = _make_client(mock_db)
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        with _auth(admin_user, "tasks.thread_status"):
            resp = client.get(f"/api/v1/tasks/thread/{uuid.uuid4()}/status", headers=AUTH_HEADERS)
        assert resp.status_code == 404

    @pytest.mark.unit
    def test_happy_path_no_active_task_can_create(self, mock_db, admin_user):
        client = _make_client(mock_db)
        thread = _mock_thread()
        channel = _mock_channel(id=thread.channel_id)
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=thread),
            _FakeResult(scalar_one_or_none=channel),
            _FakeResult(all_=[]),
        )
        with _auth(admin_user, "tasks.thread_status"):
            resp = client.get(f"/api/v1/tasks/thread/{thread.id}/status", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["can_create_task"] is True
        assert body["existing_task"] is None


# ===========================================================================
# POST /thread/{thread_id}/create (create_thread_task)
# ===========================================================================

class TestCreateThreadTask:
    @pytest.mark.unit
    def test_thread_not_found_returns_404(self, mock_db, admin_user):
        client = _make_client(mock_db)
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        with _auth(admin_user, "tasks.thread_create"):
            resp = client.post(
                f"/api/v1/tasks/thread/{uuid.uuid4()}/create",
                json={"title": "T", "message_id": str(uuid.uuid4()), "assigned_to": str(uuid.uuid4())},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 404

    @pytest.mark.unit
    def test_happy_path_creates_task_with_no_prior_messages(self, mock_db, admin_user):
        client = _make_client(mock_db)
        thread = _mock_thread()
        channel = _mock_channel(id=thread.channel_id)
        assigned_user = _mock_user(company_id=admin_user.company_id)

        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=thread),        # thread_stmt
            _FakeResult(scalar_one_or_none=channel),        # channel_stmt
            _FakeResult(scalar_one_or_none=None),           # first_message_stmt (no messages yet)
            _FakeResult(all_=[]),                           # thread_msg_ids_stmt (.all())
            _FakeResult(scalar_one_or_none=assigned_user),  # load_task_details' assignee lookup
            _FakeResult(scalar_one_or_none=admin_user),     # load_task_details' created_by lookup
        )
        mock_db.refresh = AsyncMock(side_effect=_simulate_task_refresh)
        with _auth(admin_user, "tasks.thread_create"):
            resp = client.post(
                f"/api/v1/tasks/thread/{thread.id}/create",
                json={
                    "title": "Thread Task",
                    "message_id": str(uuid.uuid4()),
                    "assigned_to": str(assigned_user.id),
                },
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["title"] == "Thread Task"
        assert body["assigned_user"]["id"] == str(assigned_user.id)
