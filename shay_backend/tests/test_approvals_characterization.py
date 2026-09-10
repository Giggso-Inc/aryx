"""
Golden-master / characterization tests for app/routes/approvals.py.

Purpose: this file (2,150 lines, 10 endpoints) has zero existing test
coverage and is about to be split into smaller modules (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5). Before the split,
we capture the CURRENT observable behavior of every endpoint so the split
can be verified to change nothing.

These are characterization tests, not "correctness" tests: assertions match
what the code actually does today, bugs included.

Pattern follows tests/test_datasources_characterization.py exactly:
- FastAPI TestClient with `app.include_router(router, prefix=...)`.
- `app.dependency_overrides[get_db] = lambda: mock_db`.
- MagicMock/AsyncMock for services; no real DB, no real HTTP.
- `get_current_user_required` is called directly inside each endpoint body
  (not via FastAPI Depends), so it is patched per-module.

Do not modify app/routes/approvals.py from this file's tests.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _make_client(mock_db):
    from app.core.database import get_db
    from app.routes.approvals import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/approvals")
    app.dependency_overrides[get_db] = lambda: mock_db
    return TestClient(app, raise_server_exceptions=False)


def _auth(user, module):
    """Patch target for get_current_user_required as looked up in the
    given app.routes.approvals submodule (each submodule imports it
    directly, so the patch target must match the endpoint under test —
    see the module docstring's CRITICAL GOTCHA note)."""
    return patch(f"app.routes.approvals.{module}.get_current_user_required", new=AsyncMock(return_value=user))


class _FakeResult:
    def __init__(self, scalar_one_or_none=None, all_=None, scalar_val=None, first_=None):
        self._son = scalar_one_or_none
        self._all = all_ if all_ is not None else []
        self._scalar_val = scalar_val
        self._first = first_

    def scalar_one_or_none(self):
        return self._son

    def scalars(self):
        m = MagicMock()
        m.all = MagicMock(return_value=self._all)
        return m

    def first(self):
        return self._first

    def scalar(self):
        return self._scalar_val

    def all(self):
        return self._all


def _exec_seq(*results):
    return AsyncMock(side_effect=list(results))


def _user(**overrides):
    u = MagicMock()
    u.id = uuid.uuid4()
    u.name = "Test User"
    u.email_id = "user@example.com"
    u.role = "user"
    for k, v in overrides.items():
        setattr(u, k, v)
    return u


def _approval(**overrides):
    a = MagicMock()
    a.id = uuid.uuid4()
    a.message_id = uuid.uuid4()
    a.requested_by_user_id = uuid.uuid4()
    a.approver_user_id = uuid.uuid4()
    a.status = "pending"
    a.title = "Approve this"
    a.description = "desc"
    a.approval_notes = None
    a.rejection_reason = None
    a.comment = None
    a.is_active = "Y"
    a.created_at = datetime.utcnow()
    a.updated_at = datetime.utcnow()
    a.approved_at = None
    a.rejected_at = None
    a.approval_metadata = {}
    for k, v in overrides.items():
        setattr(a, k, v)
    return a


def _message(**overrides):
    m = MagicMock()
    m.id = uuid.uuid4()
    m.thread_id = uuid.uuid4()
    m.channel_id = uuid.uuid4()
    m.content = "hello world"
    for k, v in overrides.items():
        setattr(m, k, v)
    return m


def _thread(**overrides):
    t = MagicMock()
    t.id = uuid.uuid4()
    t.channel_id = uuid.uuid4()
    t.title = "Thread"
    for k, v in overrides.items():
        setattr(t, k, v)
    return t


def _channel_member(**overrides):
    cm = MagicMock()
    for k, v in overrides.items():
        setattr(cm, k, v)
    return cm


@pytest.fixture(autouse=True)
def _no_audit_log():
    """audit_log_write is imported directly by create/update/reassign/delete
    (each keeps its own module-level binding), so all four must be patched."""
    with patch("app.routes.approvals.create.audit_log_write", new=AsyncMock(return_value=None)), \
         patch("app.routes.approvals.update.audit_log_write", new=AsyncMock(return_value=None)), \
         patch("app.routes.approvals.reassign.audit_log_write", new=AsyncMock(return_value=None)), \
         patch("app.routes.approvals.delete.audit_log_write", new=AsyncMock(return_value=None)):
        yield


# ===========================================================================
# POST / — create_approval
# ===========================================================================

class TestCreateApproval:
    def _payload(self, **overrides):
        payload = {
            "message_id": str(uuid.uuid4()),
            "approver_user_id": str(uuid.uuid4()),
        }
        payload.update(overrides)
        return payload

    @pytest.mark.unit
    def test_message_not_found_returns_404(self, mock_db):
        user = _user()
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        with _auth(user, "create"):
            client = _make_client(mock_db)
            resp = client.post("/api/v1/approvals/", json=self._payload())
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Message not found"

    @pytest.mark.unit
    def test_happy_path_creates_approval(self, mock_db):
        user = _user()
        message = _message()
        thread = _thread(id=message.thread_id, channel_id=message.channel_id)
        approver = _user()
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=message),          # message lookup
            _FakeResult(scalar_one_or_none=thread),            # thread lookup
            _FakeResult(scalar_one_or_none=_channel_member()),  # approver membership check
            _FakeResult(all_=[(message.id,)]),                  # thread message ids
            _FakeResult(scalar_one_or_none=None),               # existing pending approval check
            _FakeResult(scalar_one_or_none=approver),           # approver user lookup
        )
        with _auth(user, "create"), patch(
            "app.routes.approvals.create.link_shortener_service.shorten",
            new=AsyncMock(return_value="https://short.url/x"),
        ), patch("app.routes.approvals.create.settings") as mock_settings:
            mock_settings.PLATFORM_URL = "https://platform.example.com"
            client = _make_client(mock_db)
            resp = client.post(
                "/api/v1/approvals/",
                json=self._payload(message_id=str(message.id), approver_user_id=str(approver.id)),
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "pending"
        assert body["title"].startswith("Approval for:")

    @pytest.mark.unit
    def test_duplicate_pending_approval_returns_409(self, mock_db):
        user = _user()
        message = _message()
        thread = _thread(id=message.thread_id, channel_id=message.channel_id)
        existing_approval = _approval()
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=message),
            _FakeResult(scalar_one_or_none=thread),
            _FakeResult(scalar_one_or_none=_channel_member()),
            _FakeResult(all_=[(message.id,)]),
            _FakeResult(scalar_one_or_none=existing_approval),
        )
        with _auth(user, "create"):
            client = _make_client(mock_db)
            resp = client.post("/api/v1/approvals/", json=self._payload())
        assert resp.status_code == 409


# ===========================================================================
# GET / — list_approvals
# ===========================================================================

class TestListApprovals:
    @pytest.mark.unit
    def test_no_channel_memberships_returns_empty(self, mock_db):
        user = _user()
        mock_db.execute = _exec_seq(
            _FakeResult(all_=[]),  # user_channels lookup -> no memberships
            _FakeResult(all_=[]),  # items query (empty filter path still executes)
            _FakeResult(scalar_val=0),  # count query
        )
        with _auth(user, "list"):
            client = _make_client(mock_db)
            resp = client.get("/api/v1/approvals/")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 0
        assert body["approvals"] == []


# ===========================================================================
# GET /count — get_approval_count
# ===========================================================================

class TestApprovalCount:
    @pytest.mark.unit
    def test_no_channels_returns_zero(self, mock_db):
        user = _user()
        mock_db.execute = _exec_seq(_FakeResult(all_=[]))
        with _auth(user, "stats"):
            client = _make_client(mock_db)
            resp = client.get("/api/v1/approvals/count")
        assert resp.status_code == 200
        assert resp.json()["approval_count"] == 0


# ===========================================================================
# GET /stats — get_approval_stats
# ===========================================================================

class TestApprovalStats:
    @pytest.mark.unit
    def test_happy_path(self, mock_db):
        user = _user()
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_val=2),  # pending
            _FakeResult(scalar_val=3),  # approved
            _FakeResult(scalar_val=1),  # rejected
            _FakeResult(scalar_val=6),  # total
        )
        with _auth(user, "stats"):
            client = _make_client(mock_db)
            resp = client.get("/api/v1/approvals/stats")
        assert resp.status_code == 200
        body = resp.json()
        assert body == {
            "total_pending": 2,
            "total_approved": 3,
            "total_rejected": 1,
            "total_approvals": 6,
        }


# ===========================================================================
# GET /{approval_id} — get_approval
# ===========================================================================

class TestGetApproval:
    @pytest.mark.unit
    def test_not_found_returns_404(self, mock_db):
        user = _user()
        mock_db.execute = _exec_seq(_FakeResult(first_=None))
        with _auth(user, "detail"):
            client = _make_client(mock_db)
            resp = client.get(f"/api/v1/approvals/{uuid.uuid4()}")
        assert resp.status_code == 404

    @pytest.mark.unit
    def test_access_denied_for_non_participant_non_member(self, mock_db):
        user = _user()
        approval = _approval(
            requested_by_user_id=uuid.uuid4(),
            approver_user_id=uuid.uuid4(),
            message_id=None,
        )
        row = (approval, "req name", "req@x.com", "app name", "app@x.com")
        mock_db.execute = _exec_seq(_FakeResult(first_=row))
        with _auth(user, "detail"):
            client = _make_client(mock_db)
            resp = client.get(f"/api/v1/approvals/{approval.id}")
        assert resp.status_code == 403

    @pytest.mark.unit
    def test_happy_path_as_requester(self, mock_db):
        user = _user()
        approval = _approval(requested_by_user_id=user.id, message_id=None)
        row = (approval, "req name", "req@x.com", "app name", "app@x.com")
        mock_db.execute = _exec_seq(_FakeResult(first_=row))
        with _auth(user, "detail"):
            client = _make_client(mock_db)
            resp = client.get(f"/api/v1/approvals/{approval.id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == str(approval.id)


# ===========================================================================
# PUT /{approval_id} — update_approval
# ===========================================================================

class TestUpdateApproval:
    @pytest.mark.unit
    def test_not_found_returns_404(self, mock_db):
        user = _user()
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        with _auth(user, "update"):
            client = _make_client(mock_db)
            resp = client.put(f"/api/v1/approvals/{uuid.uuid4()}", json={"title": "New"})
        assert resp.status_code == 404

    @pytest.mark.unit
    def test_forbidden_for_non_participant(self, mock_db):
        user = _user()
        approval = _approval(requested_by_user_id=uuid.uuid4(), approver_user_id=uuid.uuid4())
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=approval))
        with _auth(user, "update"):
            client = _make_client(mock_db)
            resp = client.put(f"/api/v1/approvals/{approval.id}", json={"title": "New"})
        assert resp.status_code == 403

    @pytest.mark.unit
    def test_only_pending_can_be_updated(self, mock_db):
        user = _user()
        approval = _approval(requested_by_user_id=user.id, status="approved")
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=approval))
        with _auth(user, "update"):
            client = _make_client(mock_db)
            resp = client.put(f"/api/v1/approvals/{approval.id}", json={"title": "New"})
        assert resp.status_code == 400

    @pytest.mark.unit
    def test_happy_path_updates_title(self, mock_db):
        user = _user()
        approval = _approval(requested_by_user_id=user.id)
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=approval))
        with _auth(user, "update"):
            client = _make_client(mock_db)
            resp = client.put(f"/api/v1/approvals/{approval.id}", json={"title": "New Title"})
        assert resp.status_code == 200
        assert resp.json()["title"] == "New Title"


# ===========================================================================
# POST /{approval_id}/action — take_approval_action
# ===========================================================================

class TestTakeApprovalAction:
    @pytest.mark.unit
    def test_not_approver_returns_403(self, mock_db):
        user = _user()
        approval = _approval(approver_user_id=uuid.uuid4())
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=approval))
        with _auth(user, "action"):
            client = _make_client(mock_db)
            resp = client.post(
                f"/api/v1/approvals/{approval.id}/action", json={"action": "approve"}
            )
        assert resp.status_code == 403

    @pytest.mark.unit
    def test_happy_path_approve(self, mock_db):
        user = _user()
        approval = _approval(approver_user_id=user.id)
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=approval))
        with _auth(user, "action"):
            client = _make_client(mock_db)
            resp = client.post(
                f"/api/v1/approvals/{approval.id}/action",
                json={"action": "approve", "comment": "lgtm"},
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "approved"

    @pytest.mark.unit
    def test_happy_path_reject(self, mock_db):
        user = _user()
        approval = _approval(approver_user_id=user.id)
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=approval))
        with _auth(user, "action"):
            client = _make_client(mock_db)
            resp = client.post(
                f"/api/v1/approvals/{approval.id}/action",
                json={"action": "reject", "rejection_reason": "no"},
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "rejected"


# ===========================================================================
# GET /{approval_id}/debug — debug_approval_metadata
# ===========================================================================

class TestDebugApprovalMetadata:
    @pytest.mark.unit
    def test_not_found_returns_404(self, mock_db):
        user = _user()
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        with _auth(user, "history"):
            client = _make_client(mock_db)
            resp = client.get(f"/api/v1/approvals/{uuid.uuid4()}/debug")
        assert resp.status_code == 404

    @pytest.mark.unit
    def test_happy_path(self, mock_db):
        user = _user()
        approval = _approval(approval_metadata={"reassignments": [1], "status_changes": []})
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=approval))
        with _auth(user, "history"):
            client = _make_client(mock_db)
            resp = client.get(f"/api/v1/approvals/{approval.id}/debug")
        assert resp.status_code == 200
        body = resp.json()
        assert body["reassignments_count"] == 1
        assert body["status_changes_count"] == 0


# ===========================================================================
# GET /{approval_id}/history — get_approval_history
# ===========================================================================

class TestApprovalHistory:
    @pytest.mark.unit
    def test_access_denied(self, mock_db):
        user = _user()
        approval = _approval(
            requested_by_user_id=uuid.uuid4(), approver_user_id=uuid.uuid4(), message_id=None
        )
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=approval))
        with _auth(user, "history"):
            client = _make_client(mock_db)
            resp = client.get(f"/api/v1/approvals/{approval.id}/history")
        assert resp.status_code == 403

    @pytest.mark.unit
    def test_happy_path_returns_created_fallback_entry(self, mock_db):
        user = _user()
        approval = _approval(requested_by_user_id=user.id, message_id=None)
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=approval))
        with _auth(user, "history"):
            client = _make_client(mock_db)
            resp = client.get(f"/api/v1/approvals/{approval.id}/history")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        assert body[0]["action"] == "created"


# ===========================================================================
# POST /{approval_id}/reassign — reassign_approval
# ===========================================================================

class TestReassignApproval:
    @pytest.mark.unit
    def test_not_approver_returns_403(self, mock_db):
        user = _user()
        approval = _approval(approver_user_id=uuid.uuid4())
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=approval))
        with _auth(user, "reassign"):
            client = _make_client(mock_db)
            resp = client.post(
                f"/api/v1/approvals/{approval.id}/reassign",
                json={"new_approver_user_id": str(uuid.uuid4())},
            )
        assert resp.status_code == 403

    @pytest.mark.unit
    def test_happy_path_no_message_skips_membership_check(self, mock_db):
        user = _user()
        new_approver_id = uuid.uuid4()
        approval = _approval(approver_user_id=user.id, message_id=None)
        new_approver = _user(id=new_approver_id)
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=approval),       # approval lookup
            _FakeResult(scalar_one_or_none=user),            # previous approver lookup
            _FakeResult(scalar_one_or_none=new_approver),     # new approver lookup
        )
        with _auth(user, "reassign"):
            client = _make_client(mock_db)
            resp = client.post(
                f"/api/v1/approvals/{approval.id}/reassign",
                json={"new_approver_user_id": str(new_approver_id), "notes": "please review"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["approver_user_id"] == str(new_approver_id)


# ===========================================================================
# DELETE /{approval_id} — delete_approval
# ===========================================================================

class TestDeleteApproval:
    @pytest.mark.unit
    def test_only_requester_can_delete(self, mock_db):
        user = _user()
        approval = _approval(requested_by_user_id=uuid.uuid4())
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=approval))
        with _auth(user, "delete"):
            client = _make_client(mock_db)
            resp = client.delete(f"/api/v1/approvals/{approval.id}")
        assert resp.status_code == 403

    @pytest.mark.unit
    def test_happy_path_soft_deletes(self, mock_db):
        user = _user()
        approval = _approval(requested_by_user_id=user.id)
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=approval))
        with _auth(user, "delete"):
            client = _make_client(mock_db)
            resp = client.delete(f"/api/v1/approvals/{approval.id}")
        assert resp.status_code == 200
        assert resp.json()["message"] == "Approval deleted successfully"
        assert approval.is_active == "N"
