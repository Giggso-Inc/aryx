"""
Golden-master / characterization tests for app/routes/channels.py.

Purpose: channels.py is 2,630 lines with 16 endpoints and had ZERO real test
coverage before this file (tests/test_gg_channels.py targets the unrelated
app/routes/gg_channels.py module — confirmed by reading its imports, which
pull `from app.routes.gg_channels import router as ch_router`). It is about
to be split into a package (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5). Before the split,
we capture the CURRENT observable behavior of every endpoint so the split
can be verified to change nothing.

These are characterization tests, not "correctness" tests: assertions match
what the code actually does today, bugs included. E.g. Channel.is_accessible_by_user()
is hardcoded to always return True, so the "access denied" 403 branches in
update_channel/delete_channel are unreachable through the real model and are
only exercised here by monkeypatching that method on the mock Channel.

Pattern follows tests/test_datasources_characterization.py exactly:
- FastAPI TestClient with `app.include_router(router, prefix=...)`.
- `app.dependency_overrides[get_db] = lambda: mock_db`.
- MagicMock/AsyncMock for services; no real DB, no real HTTP.
- `asyncio.run()` instead of pytest-asyncio (no async plugin installed).

Do not modify app/routes/channels.py from this file's tests.
"""

from __future__ import annotations

import io
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _make_client(mock_db):
    from app.core.database import get_db
    from app.routes.channels import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/channels")
    app.dependency_overrides[get_db] = lambda: mock_db
    return TestClient(app, raise_server_exceptions=False)


AUTH_HEADERS = {"Authorization": "Bearer test-token"}


def _auth(user, module):
    """Patch get_current_user_required on the specific submodule that owns
    the endpoint under test. Each submodule in app/routes/channels/ imports
    get_current_user_required itself, so patching the package (
    app.routes.channels.get_current_user_required) would NOT affect the
    submodule's own bound reference — this is the split's "CRITICAL GOTCHA"
    from the compliance plan: patch the exact module path, not the
    re-exporting package.
    """
    return patch(f"app.routes.channels.{module}.get_current_user_required", new=AsyncMock(return_value=user))


class _FakeResult:
    """Mimics the subset of SQLAlchemy's async Result API these endpoints
    call: .scalar_one_or_none(), .scalars().all()/.first(), .scalar(),
    .first(), and plain iteration."""

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
        m.first = MagicMock(return_value=self._all[0] if self._all else None)
        return m

    def scalar(self):
        return self._scalar_val

    def first(self):
        return self._first

    def fetchone(self):
        return self._first

    def all(self):
        return self._rows if self._rows else self._all

    def __iter__(self):
        return iter(self._rows)


def _exec_seq(*results):
    return AsyncMock(side_effect=list(results))


def _simulate_refresh(obj):
    """Fills in Column defaults that a real DB applies on INSERT (is_active,
    message_count, ...). Our mock_db.refresh() is a no-op AsyncMock, so
    without this a freshly-constructed Channel/ChannelMember ORM object has
    these attributes as None, unlike what happens against a real database."""
    defaults = {
        "is_active": True,
        "message_count": 0,
        "channel_type": 1,
    }
    for key, val in defaults.items():
        if getattr(obj, key, "unset") is None:
            setattr(obj, key, val)


def _uid():
    return uuid.uuid4()


def _mock_channel(**overrides):
    ch = MagicMock()
    ch.id = _uid()
    ch.name = "general"
    ch.description = None
    ch.channel_tags = None
    ch.channel_sub_tags = None
    ch.workspace_id = _uid()
    ch.company_id = "company-001"
    ch.is_active = True
    ch.is_public = False
    ch.is_archived = False
    ch.ai_enabled = True
    ch.channel_settings = None
    ch.message_count = 0
    ch.last_message_at = None
    ch.channel_type = None
    ch.created_at = datetime.utcnow()
    ch.updated_at = datetime.utcnow()
    ch.is_accessible_by_user = MagicMock(return_value=True)
    for k, v in overrides.items():
        setattr(ch, k, v)
    return ch


def _mock_workspace(**overrides):
    ws = MagicMock()
    ws.id = _uid()
    ws.name = "eng"
    ws.description = "desc"
    ws.company_id = "company-001"
    ws.is_active = True
    ws.is_public = False
    ws.ai_enabled = True
    ws.created_at = datetime.utcnow()
    ws.updated_at = datetime.utcnow()
    for k, v in overrides.items():
        setattr(ws, k, v)
    return ws


def _mock_member(**overrides):
    m = MagicMock()
    m.id = _uid()
    m.channel_id = _uid()
    m.user_id = "user-member-002"
    m.role = "user"
    m.is_active = True
    m.permissions = {}
    m.created_at = datetime.utcnow()
    m.updated_at = datetime.utcnow()
    for k, v in overrides.items():
        setattr(m, k, v)
    return m


def _mock_user_row(**overrides):
    u = MagicMock()
    u.id = "user-member-002"
    u.email_id = "member@example.com"
    u.name = "Regular User"
    u.avatar_url = None
    u.role = "user"
    u.company_id = "company-001"
    u.is_active = True
    for k, v in overrides.items():
        setattr(u, k, v)
    return u


@pytest.fixture
def admin_user(admin_user):
    admin_user.is_admin = True
    return admin_user


@pytest.fixture
def regular_user(regular_user):
    regular_user.is_admin = False
    return regular_user


# ===========================================================================
# POST / — create_channel
# ===========================================================================

class TestCreateChannel:
    def _payload(self, **overrides):
        payload = {"name": "support", "workspace_id": str(_uid())}
        payload.update(overrides)
        return payload

    def test_insufficient_permission_403(self, mock_db, regular_user):
        client = _make_client(mock_db)
        with _auth(regular_user, "create"):
            resp = client.post("/api/v1/channels/", json=self._payload(), headers=AUTH_HEADERS)
        assert resp.status_code == 403

    def test_missing_workspace_tag_and_id_400(self, mock_db, admin_user):
        client = _make_client(mock_db)
        with _auth(admin_user, "create"):
            resp = client.post("/api/v1/channels/", json={"name": "support"}, headers=AUTH_HEADERS)
        assert resp.status_code == 400
        assert "Either workspace_tag or workspace_id" in resp.json()["detail"]

    def test_both_workspace_tag_and_id_400(self, mock_db, admin_user):
        client = _make_client(mock_db)
        payload = self._payload(workspace_tag="eng")
        with _auth(admin_user, "create"):
            resp = client.post("/api/v1/channels/", json=payload, headers=AUTH_HEADERS)
        assert resp.status_code == 400
        assert "Cannot provide both" in resp.json()["detail"]

    def test_invalid_workspace_id_format_400(self, mock_db, admin_user):
        client = _make_client(mock_db)
        with _auth(admin_user, "create"):
            resp = client.post("/api/v1/channels/", json=self._payload(workspace_id="not-a-uuid"), headers=AUTH_HEADERS)
        assert resp.status_code == 400
        assert "Invalid workspace_id format" in resp.json()["detail"]

    def test_workspace_not_found_404(self, mock_db, admin_user):
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        client = _make_client(mock_db)
        with _auth(admin_user, "create"):
            resp = client.post("/api/v1/channels/", json=self._payload(), headers=AUTH_HEADERS)
        assert resp.status_code == 404

    def test_duplicate_channel_name_409(self, mock_db, admin_user):
        workspace = _mock_workspace()
        existing_channel = _mock_channel(name="support")
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=workspace),
            _FakeResult(scalar_one_or_none=existing_channel),
        )
        client = _make_client(mock_db)
        with _auth(admin_user, "create"):
            resp = client.post("/api/v1/channels/", json=self._payload(), headers=AUTH_HEADERS)
        assert resp.status_code == 409

    def test_create_with_existing_workspace_id_happy_path(self, mock_db, admin_user):
        workspace = _mock_workspace()
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=workspace),
            _FakeResult(scalar_one_or_none=None),
        )
        mock_db.refresh = AsyncMock(side_effect=_simulate_refresh)
        client = _make_client(mock_db)
        with _auth(admin_user, "create"), patch("app.routes.channels.create.audit_log_write", new=AsyncMock()):
            resp = client.post("/api/v1/channels/", json=self._payload(), headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "support"
        assert body["total_users"] == 1
        assert body["workspace_name"] == workspace.name

    def test_create_with_new_workspace_tag_happy_path(self, mock_db, admin_user):
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=None),  # workspace lookup by tag -> not found
            _FakeResult(scalar_one_or_none=None),  # duplicate channel check
        )
        mock_db.refresh = AsyncMock(side_effect=_simulate_refresh)
        client = _make_client(mock_db)
        with _auth(admin_user, "create"), patch("app.routes.channels.create.audit_log_write", new=AsyncMock()):
            resp = client.post(
                "/api/v1/channels/",
                json={"name": "support", "workspace_tag": "newtag"},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 200
        assert resp.json()["workspace_name"] == "newtag"


# ===========================================================================
# GET / — list_channels
# ===========================================================================

class TestListChannels:
    def test_happy_path_empty(self, mock_db, admin_user):
        mock_db.execute = _exec_seq(
            _FakeResult(all_=[]),           # main query
            _FakeResult(scalar_val=0),      # count query
            _FakeResult(scalar_val=0),      # archived-count query (is_archived default False)
        )
        client = _make_client(mock_db)
        with _auth(admin_user, "list_my"):
            resp = client.get("/api/v1/channels/", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["channels"] == []
        assert body["total"] == 0
        assert body["has_archived_channels"] is False

    def test_happy_path_with_one_channel_hits_preexisting_approval_bug(self, mock_db, admin_user):
        """Characterization of a real pre-existing bug: app/models/approval.py's
        Approval model has no `channel_id` column (only message_id), but every
        per-channel metrics block in channels.py builds
        `Approval.channel_id == ...` — an AttributeError raised while building
        the query, before db.execute is even reached. So list_channels (like
        get_channel/update_channel/delete_channel) 500s for any company that
        actually has a channel in the result set. Documented as-is, not fixed."""
        channel = _mock_channel()
        mock_db.execute = _exec_seq(
            _FakeResult(rows=[(channel, "eng")]),  # main join query -> tuples
            _FakeResult(scalar_val=1),             # count
            _FakeResult(scalar_val=0),             # archived_count (is_archived=False by default)
            _FakeResult(scalar_val=0),             # apps_count
            _FakeResult(scalar_val=1),             # users_count
            _FakeResult(scalar_val=0),             # datasources_count
            _FakeResult(scalar_val=0),             # tasks_count
            # No result for approvals_count: building `Approval.channel_id`
            # raises AttributeError before db.execute is called for it.
        )
        client = _make_client(mock_db)
        with _auth(admin_user, "list_my"):
            resp = client.get("/api/v1/channels/", headers=AUTH_HEADERS)
        assert resp.status_code == 500


# ===========================================================================
# GET /message-channels — list_message_channels
# ===========================================================================

class TestListMessageChannels:
    def test_missing_workspace_id_422(self, mock_db, admin_user):
        client = _make_client(mock_db)
        with _auth(admin_user, "list_message"):
            resp = client.get("/api/v1/channels/message-channels", headers=AUTH_HEADERS)
        assert resp.status_code == 422

    def test_happy_path_empty(self, mock_db, admin_user):
        mock_db.execute = _exec_seq(_FakeResult(rows=[]))
        client = _make_client(mock_db)
        with _auth(admin_user, "list_message"):
            resp = client.get(
                f"/api/v1/channels/message-channels?workspace_id={_uid()}",
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 200
        assert resp.json() == []


# ===========================================================================
# GET /company — list_company_channels
# ===========================================================================

class TestListCompanyChannels:
    def test_happy_path_empty(self, mock_db, admin_user):
        mock_db.execute = _exec_seq(
            _FakeResult(rows=[]),
            _FakeResult(scalar_val=0),
        )
        client = _make_client(mock_db)
        with _auth(admin_user, "list_company"):
            resp = client.get("/api/v1/channels/company", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["channels"] == []
        assert body["total"] == 0


# ===========================================================================
# GET /my-memberships — list_my_channel_memberships
# ===========================================================================

class TestListMyChannelMemberships:
    def test_happy_path_empty(self, mock_db, admin_user):
        mock_db.execute = _exec_seq(
            _FakeResult(rows=[]),
            _FakeResult(scalar_val=0),
        )
        client = _make_client(mock_db)
        with _auth(admin_user, "list_memberships"):
            resp = client.get("/api/v1/channels/my-memberships", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        assert resp.json()["total"] == 0


# ===========================================================================
# GET /tags — list_workspace_tags
# ===========================================================================

class TestListWorkspaceTags:
    def test_happy_path(self, mock_db, admin_user):
        workspace = _mock_workspace()
        mock_db.execute = _exec_seq(
            _FakeResult(rows=[(workspace, 3)]),
            _FakeResult(scalar_val=1),
        )
        client = _make_client(mock_db)
        with _auth(admin_user, "tags"):
            resp = client.get("/api/v1/channels/tags", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["tags"][0]["channel_count"] == 3


# ===========================================================================
# GET /workspaces — list_workspaces
# ===========================================================================

class TestListWorkspaces:
    def test_happy_path(self, mock_db, admin_user):
        workspace = _mock_workspace()
        mock_db.execute = _exec_seq(
            _FakeResult(rows=[(workspace, 0)]),
            _FakeResult(scalar_val=1),
        )
        client = _make_client(mock_db)
        with _auth(admin_user, "tags"):
            resp = client.get("/api/v1/channels/workspaces", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        assert resp.json()["tags"][0]["name"] == workspace.name


# ===========================================================================
# GET /{channel_id} — get_channel
# ===========================================================================

class TestGetChannel:
    def test_channel_not_found_404(self, mock_db, admin_user):
        mock_db.execute = _exec_seq(_FakeResult(first_=None))
        client = _make_client(mock_db)
        with _auth(admin_user, "detail"), patch("app.routes.channels.detail.check_channel_access", new=AsyncMock(return_value=True)):
            resp = client.get(f"/api/v1/channels/{_uid()}", headers=AUTH_HEADERS)
        assert resp.status_code == 404

    def test_invalid_uuid_400(self, mock_db, admin_user):
        client = _make_client(mock_db)
        with _auth(admin_user, "detail"), patch("app.routes.channels.detail.check_channel_access", new=AsyncMock(return_value=True)):
            resp = client.get("/api/v1/channels/not-a-uuid", headers=AUTH_HEADERS)
        assert resp.status_code == 400

    def test_happy_path_hits_preexisting_approval_bug(self, mock_db, admin_user):
        """See TestListChannels' equivalent test: Approval.channel_id does
        not exist, so get_channel's approval_count query 500s (unhandled,
        plain-text "Internal Server Error" since this endpoint has no
        try/except) for any existing channel. Documented as-is."""
        channel = _mock_channel()
        mock_db.execute = _exec_seq(
            _FakeResult(first_=(channel, "eng")),
            _FakeResult(scalar_val=0),  # apps
            _FakeResult(scalar_val=1),  # users
            _FakeResult(scalar_val=0),  # datasources
            _FakeResult(scalar_val=0),  # tasks
            # approvals_count query building raises before execute
        )
        client = _make_client(mock_db)
        with _auth(admin_user, "detail"), patch("app.routes.channels.detail.check_channel_access", new=AsyncMock(return_value=True)):
            resp = client.get(f"/api/v1/channels/{channel.id}", headers=AUTH_HEADERS)
        assert resp.status_code == 500


# ===========================================================================
# GET /{channel_id}/access — check_user_access
# ===========================================================================

class TestCheckUserAccess:
    def test_channel_not_found_404(self, mock_db, admin_user):
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        client = _make_client(mock_db)
        with _auth(admin_user, "detail"):
            resp = client.get(f"/api/v1/channels/{_uid()}/access", headers=AUTH_HEADERS)
        assert resp.status_code == 404

    def test_admin_has_access(self, mock_db, admin_user):
        channel = _mock_channel()
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=channel))
        client = _make_client(mock_db)
        admin_user.is_admin = True
        with _auth(admin_user, "detail"):
            resp = client.get(f"/api/v1/channels/{channel.id}/access", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        assert resp.json() == {"has_access": True, "reason": "admin"}

    def test_company_mismatch(self, mock_db, regular_user):
        channel = _mock_channel(company_id="other-company")
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=channel))
        client = _make_client(mock_db)
        with _auth(regular_user, "detail"):
            resp = client.get(f"/api/v1/channels/{channel.id}/access", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        assert resp.json() == {"has_access": False, "reason": "company_mismatch"}

    def test_public_channel_access(self, mock_db, regular_user):
        channel = _mock_channel(company_id="company-001", is_public=True)
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=channel))
        client = _make_client(mock_db)
        with _auth(regular_user, "detail"):
            resp = client.get(f"/api/v1/channels/{channel.id}/access", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        assert resp.json() == {"has_access": True, "reason": "public"}

    def test_member_access(self, mock_db, regular_user):
        channel = _mock_channel(company_id="company-001", is_public=False)
        member = _mock_member(user_id=regular_user.id)
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=channel),
            _FakeResult(scalar_one_or_none=member),
        )
        client = _make_client(mock_db)
        with _auth(regular_user, "detail"):
            resp = client.get(f"/api/v1/channels/{channel.id}/access", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        assert resp.json() == {"has_access": True, "reason": "member"}

    def test_not_member(self, mock_db, regular_user):
        channel = _mock_channel(company_id="company-001", is_public=False)
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=channel),
            _FakeResult(scalar_one_or_none=None),
        )
        client = _make_client(mock_db)
        with _auth(regular_user, "detail"):
            resp = client.get(f"/api/v1/channels/{channel.id}/access", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        assert resp.json() == {"has_access": False, "reason": "not_member"}


# ===========================================================================
# POST /{channel_id}/members — add_channel_member
# ===========================================================================

class TestAddChannelMember:
    def test_channel_not_found_404(self, mock_db, admin_user):
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        client = _make_client(mock_db)
        with _auth(admin_user, "members_single"):
            resp = client.post(
                f"/api/v1/channels/{_uid()}/members",
                json={"mail_id": "x@example.com", "role": "user"},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 404

    def test_cross_company_403(self, mock_db, regular_user):
        channel = _mock_channel(company_id="other-company")
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=channel))
        client = _make_client(mock_db)
        with _auth(regular_user, "members_single"):
            resp = client.post(
                f"/api/v1/channels/{channel.id}/members",
                json={"mail_id": "x@example.com", "role": "user"},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 403

    def test_insufficient_permission_403(self, mock_db, regular_user):
        channel = _mock_channel(company_id="company-001")
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=channel))
        client = _make_client(mock_db)
        with _auth(regular_user, "members_single"):
            resp = client.post(
                f"/api/v1/channels/{channel.id}/members",
                json={"mail_id": "x@example.com", "role": "user"},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 403

    def test_user_not_found_404(self, mock_db, admin_user):
        channel = _mock_channel(company_id="company-001")
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=channel),
            _FakeResult(scalar_one_or_none=None),
        )
        client = _make_client(mock_db)
        with _auth(admin_user, "members_single"):
            resp = client.post(
                f"/api/v1/channels/{channel.id}/members",
                json={"mail_id": "nobody@example.com", "role": "user"},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 404

    def test_create_new_member_happy_path(self, mock_db, admin_user):
        channel = _mock_channel(company_id="company-001")
        target_user = _mock_user_row()
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=channel),
            _FakeResult(scalar_one_or_none=target_user),
            _FakeResult(scalar_one_or_none=None),  # not already a member
            _FakeResult(all_=[]),  # get_channel_admins: admin_members
        )
        client = _make_client(mock_db)
        with _auth(admin_user, "members_single"), \
                patch("app.routes.channels.members_single.audit_log_write", new=AsyncMock()), \
                patch("app.routes.channels.members_single.email_service.send_channel_member_notification", return_value=True):
            resp = client.post(
                f"/api/v1/channels/{channel.id}/members",
                json={"mail_id": "member@example.com", "role": "user"},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["user_id"] == str(target_user.id)
        assert body["role"] == "user"

    def test_update_existing_member_upsert(self, mock_db, admin_user):
        channel = _mock_channel(company_id="company-001")
        target_user = _mock_user_row()
        existing = _mock_member(user_id=target_user.id, role="user")
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=channel),
            _FakeResult(scalar_one_or_none=target_user),
            _FakeResult(scalar_one_or_none=existing),
        )
        client = _make_client(mock_db)
        with _auth(admin_user, "members_single"), patch("app.routes.channels.members_single.audit_log_write", new=AsyncMock()):
            resp = client.post(
                f"/api/v1/channels/{channel.id}/members",
                json={"mail_id": "member@example.com", "role": "admin"},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 200
        assert resp.json()["role"] == "admin"
        assert existing.role == "admin"


# ===========================================================================
# GET /{channel_id}/members — list_channel_members
# ===========================================================================

class TestListChannelMembers:
    def test_channel_not_found_404(self, mock_db, admin_user):
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        client = _make_client(mock_db)
        with _auth(admin_user, "members_single"), patch("app.routes.channels.members_single.check_channel_access", new=AsyncMock(return_value=True)):
            resp = client.get(f"/api/v1/channels/{_uid()}/members", headers=AUTH_HEADERS)
        assert resp.status_code == 404

    def test_happy_path_empty(self, mock_db, admin_user):
        channel = _mock_channel()
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=channel),
            _FakeResult(rows=[]),
            _FakeResult(scalar_val=0),
        )
        client = _make_client(mock_db)
        with _auth(admin_user, "members_single"), patch("app.routes.channels.members_single.check_channel_access", new=AsyncMock(return_value=True)):
            resp = client.get(f"/api/v1/channels/{channel.id}/members", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        assert resp.json() == {"items": [], "total": 0}


# ===========================================================================
# PUT /{channel_id}/members/{update_user_id} — update_channel_member
# ===========================================================================

class TestUpdateChannelMember:
    def test_not_admin_403(self, mock_db, regular_user):
        client = _make_client(mock_db)
        with _auth(regular_user, "members_admin"):
            resp = client.put(
                f"/api/v1/channels/{_uid()}/members/{_uid()}",
                json={"role": "admin"},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 403

    def test_channel_not_found_404(self, mock_db, admin_user):
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        client = _make_client(mock_db)
        with _auth(admin_user, "members_admin"):
            resp = client.put(
                f"/api/v1/channels/{_uid()}/members/{_uid()}",
                json={"role": "admin"},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 404

    def test_member_not_found_404(self, mock_db, admin_user):
        channel = _mock_channel()
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=channel),
            _FakeResult(scalar_one_or_none=None),
        )
        client = _make_client(mock_db)
        with _auth(admin_user, "members_admin"):
            resp = client.put(
                f"/api/v1/channels/{channel.id}/members/{_uid()}",
                json={"role": "admin"},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 404

    def test_happy_path(self, mock_db, admin_user):
        channel = _mock_channel()
        target_user_id = _uid()
        member = _mock_member(role="user", user_id=target_user_id)
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=channel),
            _FakeResult(scalar_one_or_none=member),
        )
        client = _make_client(mock_db)
        with _auth(admin_user, "members_admin"), patch("app.routes.channels.members_admin.audit_log_write", new=AsyncMock()):
            resp = client.put(
                f"/api/v1/channels/{channel.id}/members/{target_user_id}",
                json={"role": "admin"},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 200
        assert resp.json()["updated_member"]["role"] == "admin"
        assert member.role == "admin"


# ===========================================================================
# DELETE /{channel_id}/members/{delete_user_id} — remove_channel_member
# ===========================================================================

class TestRemoveChannelMember:
    def test_not_admin_403(self, mock_db, regular_user):
        client = _make_client(mock_db)
        with _auth(regular_user, "members_admin"):
            resp = client.delete(f"/api/v1/channels/{_uid()}/members/{_uid()}", headers=AUTH_HEADERS)
        assert resp.status_code == 403

    def test_member_not_found_404(self, mock_db, admin_user):
        channel = _mock_channel()
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=channel),
            _FakeResult(scalar_one_or_none=None),
        )
        client = _make_client(mock_db)
        with _auth(admin_user, "members_admin"):
            resp = client.delete(f"/api/v1/channels/{channel.id}/members/{_uid()}", headers=AUTH_HEADERS)
        assert resp.status_code == 404

    def test_happy_path(self, mock_db, admin_user):
        channel = _mock_channel()
        target_user_id = _uid()
        member = _mock_member(user_id=target_user_id)
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=channel),
            _FakeResult(scalar_one_or_none=member),
        )
        client = _make_client(mock_db)
        with _auth(admin_user, "members_admin"), patch("app.routes.channels.members_admin.audit_log_write", new=AsyncMock()):
            resp = client.delete(f"/api/v1/channels/{channel.id}/members/{target_user_id}", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        assert resp.json() == {"message": "Member removed from channel successfully"}
        mock_db.delete.assert_awaited()


# ===========================================================================
# PUT /{channel_id} — update_channel
# ===========================================================================

class TestUpdateChannel:
    def test_channel_not_found_404(self, mock_db, admin_user):
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        client = _make_client(mock_db)
        with _auth(admin_user, "mutate"):
            resp = client.put(f"/api/v1/channels/{_uid()}", json={"description": "new"}, headers=AUTH_HEADERS)
        assert resp.status_code == 404

    def test_access_denied_403(self, mock_db, admin_user):
        channel = _mock_channel()
        channel.is_accessible_by_user = MagicMock(return_value=False)
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=channel))
        client = _make_client(mock_db)
        with _auth(admin_user, "mutate"):
            resp = client.put(f"/api/v1/channels/{channel.id}", json={"description": "new"}, headers=AUTH_HEADERS)
        assert resp.status_code == 403

    def test_name_conflict_409(self, mock_db, admin_user):
        channel = _mock_channel(name="old")
        conflicting = _mock_channel(name="new-name")
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=channel),
            _FakeResult(all_=[conflicting]),
            _FakeResult(scalar_val="eng"),
        )
        client = _make_client(mock_db)
        with _auth(admin_user, "mutate"):
            resp = client.put(f"/api/v1/channels/{channel.id}", json={"name": "new-name"}, headers=AUTH_HEADERS)
        assert resp.status_code == 409

    def test_happy_path_hits_preexisting_approval_bug(self, mock_db, admin_user):
        """See TestListChannels' equivalent test: Approval.channel_id does
        not exist, so update_channel's approval_count query 500s (unhandled)
        after the update itself has already been committed. Documented as-is
        — the write succeeds but the response never comes back."""
        channel = _mock_channel(description="old")
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=channel),
            _FakeResult(scalar_val="eng"),
            _FakeResult(scalar_val=0),  # task_count
            # approval_count query building raises before execute
        )
        client = _make_client(mock_db)
        with _auth(admin_user, "mutate"), patch("app.routes.channels.mutate.audit_log_write", new=AsyncMock()):
            resp = client.put(
                f"/api/v1/channels/{channel.id}",
                json={"description": "updated description"},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 500
        # The update itself already happened (commit ran before the bug hits).
        assert channel.description == "updated description"


# ===========================================================================
# POST /{channel_id}/members/bulk-csv — add_channel_members_bulk_csv
# ===========================================================================

class TestAddChannelMembersBulkCsv:
    def _csv_file(self, content: str):
        return {"csv_file": ("members.csv", io.BytesIO(content.encode("utf-8")), "text/csv")}

    def test_channel_not_found_404(self, mock_db, admin_user):
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        client = _make_client(mock_db)
        with _auth(admin_user, "members_bulk"):
            resp = client.post(
                f"/api/v1/channels/{_uid()}/members/bulk-csv",
                files=self._csv_file("gmail_id,role\nx@example.com,user\n"),
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 404

    def test_non_csv_file_400(self, mock_db, admin_user):
        channel = _mock_channel(company_id="company-001")
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=channel))
        client = _make_client(mock_db)
        with _auth(admin_user, "members_bulk"):
            resp = client.post(
                f"/api/v1/channels/{channel.id}/members/bulk-csv",
                files={"csv_file": ("members.txt", io.BytesIO(b"x"), "text/plain")},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 400
        assert "must be a CSV" in resp.json()["detail"]

    def test_missing_columns_400(self, mock_db, admin_user):
        channel = _mock_channel(company_id="company-001")
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=channel))
        client = _make_client(mock_db)
        with _auth(admin_user, "members_bulk"):
            resp = client.post(
                f"/api/v1/channels/{channel.id}/members/bulk-csv",
                files=self._csv_file("email,perm\nx@example.com,admin\n"),
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 400
        assert "must contain" in resp.json()["detail"]

    def test_happy_path_new_member(self, mock_db, admin_user):
        channel = _mock_channel(company_id="company-001")
        target_user = _mock_user_row()
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=channel),
            _FakeResult(scalar_one_or_none=target_user),  # user lookup by gmail_id
            _FakeResult(scalar_one_or_none=None),          # not already a member
            _FakeResult(all_=[target_user]),               # notification: refetch users by id
            _FakeResult(all_=[]),                           # get_channel_admins: admin_members (not_used, but branch below is accsell so skipped)
        )
        client = _make_client(mock_db)
        with _auth(admin_user, "members_bulk"), \
                patch("app.routes.channels.members_bulk.audit_log_write", new=AsyncMock()), \
                patch("app.routes.channels.members_bulk.email_service.send_channel_member_notification", return_value=True):
            resp = client.post(
                f"/api/v1/channels/{channel.id}/members/bulk-csv?platform_name=accsell",
                files=self._csv_file(f"gmail_id,role\n{target_user.email_id},user\n"),
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert "Successfully added 1 members" in body["message"]

    def test_user_not_in_db_reports_error(self, mock_db, admin_user):
        channel = _mock_channel(company_id="company-001")
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=channel),
            _FakeResult(scalar_one_or_none=None),  # user not found
        )
        client = _make_client(mock_db)
        with _auth(admin_user, "members_bulk"):
            resp = client.post(
                f"/api/v1/channels/{channel.id}/members/bulk-csv",
                files=self._csv_file("gmail_id,role\nghost@example.com,user\n"),
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 0
        assert body["errors"] and "does not exist in the database" in body["errors"][0]


# ===========================================================================
# DELETE /{channel_id} — delete_channel
# ===========================================================================

class TestDeleteChannel:
    def test_channel_not_found_404(self, mock_db, admin_user):
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        client = _make_client(mock_db)
        with _auth(admin_user, "mutate"):
            resp = client.delete(f"/api/v1/channels/{_uid()}", headers=AUTH_HEADERS)
        assert resp.status_code == 404

    def test_access_denied_403(self, mock_db, admin_user):
        channel = _mock_channel()
        channel.is_accessible_by_user = MagicMock(return_value=False)
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=channel))
        client = _make_client(mock_db)
        with _auth(admin_user, "mutate"):
            resp = client.delete(f"/api/v1/channels/{channel.id}", headers=AUTH_HEADERS)
        assert resp.status_code == 403

    def test_happy_path_hits_preexisting_approval_bug(self, mock_db, admin_user):
        """delete_channel's very first cascading step is
        `select(Approval).where(Approval.channel_id == channel_uuid)`, which
        raises AttributeError while building the query (Approval has no
        channel_id column — see the equivalent list_channels/get_channel
        tests). Unlike those two endpoints, delete_channel wraps the whole
        cascade in try/except Exception and rolls back, returning a 500 with
        a JSON detail message instead of crashing raw. Documented as-is:
        deleting a channel is currently completely broken in this codebase."""
        channel = _mock_channel()
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=channel),  # get channel
            # approvals_stmt build raises before execute is reached
        )
        client = _make_client(mock_db)
        with _auth(admin_user, "mutate"), patch("app.routes.channels.mutate.audit_log_write", new=AsyncMock()):
            resp = client.delete(f"/api/v1/channels/{channel.id}", headers=AUTH_HEADERS)
        assert resp.status_code == 500
        assert "Approval" in resp.json()["detail"]
        mock_db.rollback.assert_awaited()
