"""
Golden-master / characterization tests for app/routes/notifications.py.

Purpose: notifications.py is 768 lines with 7 endpoints and had ZERO test
coverage before this file. It is about to be split into a package (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5). Before the split,
we capture the CURRENT observable behavior of every endpoint so the split
can be verified to change nothing.

These are characterization tests, not "correctness" tests: assertions match
what the code actually does today, bugs included. Notably:
- `current_user.is_admin` is accessed directly (not `.role`). The shared
  `admin_user`/`regular_user` fixtures in conftest.py only set `.role`, so
  on a bare MagicMock, `.is_admin` auto-vivifies as a truthy child Mock.
  That means `not current_user.is_admin` is False for BOTH fixtures unless
  the test explicitly sets `.is_admin`, and every permission-check branch
  gated behind `if not current_user.is_admin:` is skipped by default. Tests
  below set `.is_admin` explicitly wherever the branch under test needs it.
- `get_current_user_required` is awaited directly (not via `Depends`), so
  it is patched at the module level, not overridden via
  `app.dependency_overrides`.

Pattern follows tests/test_channels_characterization.py:
- FastAPI TestClient with `app.include_router(router, prefix=...)`.
- `app.dependency_overrides[get_db] = lambda: mock_db`.
- MagicMock/AsyncMock for services; no real DB, no real HTTP.
- `asyncio.run()` is not needed here since TestClient handles the loop, but
  no pytest-asyncio plugin is used anywhere in this suite.

Do not modify app/routes/notifications.py from this file's tests.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient


PATCH_TARGET = "app.routes.notifications.realtime.get_current_user_required"
PATCH_TARGET_EMAIL = "app.routes.notifications.email_settings.get_current_user_required"


def _make_client(mock_db):
    from app.core.database import get_db
    from app.routes.notifications import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/notifications")
    app.dependency_overrides[get_db] = lambda: mock_db
    return TestClient(app, raise_server_exceptions=False)


def _auth(user, target=PATCH_TARGET):
    return patch(target, new=AsyncMock(return_value=user))


class _FakeResult:
    """Mimics the subset of SQLAlchemy's async Result API used here:
    .scalar_one_or_none()."""

    def __init__(self, scalar_one_or_none=None):
        self._son = scalar_one_or_none

    def scalar_one_or_none(self):
        return self._son


def _mk_user(company_id="company-001", is_admin=False):
    u = MagicMock()
    u.id = "user-001"
    u.company_id = company_id
    u.is_admin = is_admin
    u.email_id = "user@example.com"
    return u


def _mk_channel(company_id="company-001", workspace_id="ws-001", is_public=True):
    c = MagicMock()
    c.id = "channel-001"
    c.workspace_id = workspace_id
    c.company_id = company_id
    c.is_public = is_public
    return c


def _mk_workspace(ws_id="ws-001"):
    w = MagicMock()
    w.id = ws_id
    return w


def _mk_notification(**overrides):
    n = MagicMock()
    n.id = "notif-001"
    n.user_id = "user-001"
    n.workspace_id = "ws-001"
    n.channel_id = "channel-001"
    n.is_notifications_enabled = True
    n.apps_enabled = ["app1"]
    n.is_post_enabled = False
    n.is_mention_enabled = True
    n.is_task_enabled = False
    n.is_approval_enabled = False
    n.is_new_email_enabled = False
    n.is_email_reply_enabled = False
    n.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    n.updated_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for k, v in overrides.items():
        setattr(n, k, v)
    return n


VALID_USER_ID = str(uuid.uuid4())
VALID_CHANNEL_ID = str(uuid.uuid4())
VALID_WORKSPACE_ID = str(uuid.uuid4())
VALID_NOTIF_ID = str(uuid.uuid4())


# ---------------------------------------------------------------------------
# GET /realTimeNotificationSettings/{userId}/{channelId}
# ---------------------------------------------------------------------------

def test_get_realtime_settings_invalid_uuid_returns_400(mock_db, regular_user):
    client = _make_client(mock_db)
    with _auth(regular_user):
        resp = client.get(f"/api/v1/notifications/realTimeNotificationSettings/not-a-uuid/{VALID_CHANNEL_ID}")
    assert resp.status_code == 400
    assert "Invalid UUID" in resp.json()["detail"]


def test_get_realtime_settings_user_not_found_returns_404(mock_db, regular_user):
    client = _make_client(mock_db)
    mock_db.execute = AsyncMock(return_value=_FakeResult(scalar_one_or_none=None))
    with _auth(regular_user):
        resp = client.get(f"/api/v1/notifications/realTimeNotificationSettings/{VALID_USER_ID}/{VALID_CHANNEL_ID}")
    assert resp.status_code == 404
    assert "User with ID" in resp.json()["detail"]


def test_get_realtime_settings_existing_returns_values(mock_db, admin_user):
    admin_user.is_admin = True
    target_user = _mk_user()
    channel = _mk_channel()
    notification = _mk_notification()
    mock_db.execute = AsyncMock(
        side_effect=[
            _FakeResult(scalar_one_or_none=target_user),
            _FakeResult(scalar_one_or_none=channel),
            _FakeResult(scalar_one_or_none=notification),
        ]
    )
    client = _make_client(mock_db)
    with _auth(admin_user):
        resp = client.get(f"/api/v1/notifications/realTimeNotificationSettings/{VALID_USER_ID}/{VALID_CHANNEL_ID}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == "notif-001"
    assert body["is_mention_enabled"] is True


def test_get_realtime_settings_missing_returns_defaults(mock_db, admin_user):
    admin_user.is_admin = True
    target_user = _mk_user()
    channel = _mk_channel()
    mock_db.execute = AsyncMock(
        side_effect=[
            _FakeResult(scalar_one_or_none=target_user),
            _FakeResult(scalar_one_or_none=channel),
            _FakeResult(scalar_one_or_none=None),
        ]
    )
    client = _make_client(mock_db)
    with _auth(admin_user):
        resp = client.get(f"/api/v1/notifications/realTimeNotificationSettings/{VALID_USER_ID}/{VALID_CHANNEL_ID}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] is None
    assert body["is_notifications_enabled"] is True
    assert body["is_mention_enabled"] is True
    assert body["is_post_enabled"] is False


def test_get_realtime_settings_non_admin_cross_company_forbidden(mock_db, regular_user):
    # Characterizes a real 403 branch: regular_user.is_admin is explicitly
    # False here, and target_user's company differs from channel's company.
    regular_user.is_admin = False
    target_user = _mk_user(company_id="other-company")
    channel = _mk_channel(company_id="company-001")
    mock_db.execute = AsyncMock(
        side_effect=[
            _FakeResult(scalar_one_or_none=target_user),
            _FakeResult(scalar_one_or_none=channel),
        ]
    )
    client = _make_client(mock_db)
    with _auth(regular_user):
        resp = client.get(f"/api/v1/notifications/realTimeNotificationSettings/{VALID_USER_ID}/{VALID_CHANNEL_ID}")
    assert resp.status_code == 403
    assert "does not belong to this channel" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# POST /save
# ---------------------------------------------------------------------------

REALTIME_SAVE_PAYLOAD = {
    "workspace_id": VALID_WORKSPACE_ID,
    "channel_id": VALID_CHANNEL_ID,
    "is_notifications_enabled": True,
    "apps_enabled": ["app1"],
    "is_post_enabled": False,
    "is_mention_enabled": True,
    "is_task_enabled": False,
    "is_approval_enabled": False,
    "is_new_email_enabled": False,
    "is_email_reply_enabled": False,
}


def test_save_realtime_settings_invalid_uuid_returns_400(mock_db, regular_user):
    client = _make_client(mock_db)
    payload = dict(REALTIME_SAVE_PAYLOAD, workspace_id="bad-uuid")
    with _auth(regular_user):
        resp = client.post("/api/v1/notifications/save", json=payload)
    assert resp.status_code == 400


def test_save_realtime_settings_channel_not_found_returns_404(mock_db, regular_user):
    mock_db.execute = AsyncMock(return_value=_FakeResult(scalar_one_or_none=None))
    client = _make_client(mock_db)
    with _auth(regular_user):
        resp = client.post("/api/v1/notifications/save", json=REALTIME_SAVE_PAYLOAD)
    assert resp.status_code == 404
    assert "Channel with ID" in resp.json()["detail"]


def test_save_realtime_settings_creates_new_when_absent(mock_db, admin_user):
    admin_user.is_admin = True
    channel = _mk_channel(workspace_id=VALID_WORKSPACE_ID)
    workspace = _mk_workspace(ws_id=VALID_WORKSPACE_ID)
    mock_db.execute = AsyncMock(
        side_effect=[
            _FakeResult(scalar_one_or_none=channel),
            _FakeResult(scalar_one_or_none=workspace),
            _FakeResult(scalar_one_or_none=None),  # no existing notification
        ]
    )
    client = _make_client(mock_db)
    with _auth(admin_user):
        resp = client.post("/api/v1/notifications/save", json=REALTIME_SAVE_PAYLOAD)
    assert resp.status_code == 200
    mock_db.add.assert_called_once()
    assert mock_db.commit.await_count == 1


def test_save_realtime_settings_workspace_mismatch_returns_400(mock_db, admin_user):
    admin_user.is_admin = True
    channel = _mk_channel(workspace_id="different-ws")
    workspace = _mk_workspace(ws_id=VALID_WORKSPACE_ID)
    mock_db.execute = AsyncMock(
        side_effect=[
            _FakeResult(scalar_one_or_none=channel),
            _FakeResult(scalar_one_or_none=workspace),
        ]
    )
    client = _make_client(mock_db)
    with _auth(admin_user):
        resp = client.post("/api/v1/notifications/save", json=REALTIME_SAVE_PAYLOAD)
    assert resp.status_code == 400
    assert "does not belong to the specified workspace" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# PUT /update
# ---------------------------------------------------------------------------

REALTIME_UPDATE_PAYLOAD = dict(REALTIME_SAVE_PAYLOAD, id=VALID_NOTIF_ID)


def test_update_realtime_settings_not_found_returns_404(mock_db, regular_user):
    mock_db.execute = AsyncMock(return_value=_FakeResult(scalar_one_or_none=None))
    client = _make_client(mock_db)
    with _auth(regular_user):
        resp = client.put("/api/v1/notifications/update", json=REALTIME_UPDATE_PAYLOAD)
    assert resp.status_code == 404


def test_update_realtime_settings_wrong_owner_returns_403(mock_db, regular_user):
    regular_user.id = "someone-else"
    notification = _mk_notification(user_id="user-001")
    mock_db.execute = AsyncMock(return_value=_FakeResult(scalar_one_or_none=notification))
    client = _make_client(mock_db)
    with _auth(regular_user):
        resp = client.put("/api/v1/notifications/update", json=REALTIME_UPDATE_PAYLOAD)
    assert resp.status_code == 403
    assert "only update your own" in resp.json()["detail"]


def test_update_realtime_settings_success(mock_db, admin_user):
    admin_user.is_admin = True
    notification = _mk_notification(user_id=admin_user.id)
    channel = _mk_channel(workspace_id=VALID_WORKSPACE_ID)
    workspace = _mk_workspace(ws_id=VALID_WORKSPACE_ID)
    mock_db.execute = AsyncMock(
        side_effect=[
            _FakeResult(scalar_one_or_none=notification),
            _FakeResult(scalar_one_or_none=channel),
            _FakeResult(scalar_one_or_none=workspace),
        ]
    )
    client = _make_client(mock_db)
    with _auth(admin_user):
        resp = client.put("/api/v1/notifications/update", json=REALTIME_UPDATE_PAYLOAD)
    assert resp.status_code == 200
    assert mock_db.commit.await_count == 1


# ---------------------------------------------------------------------------
# POST /emailnotifysettings/save
# ---------------------------------------------------------------------------

EMAIL_SAVE_PAYLOAD = {
    "resource_id": VALID_USER_ID,
    "routine": 60,
    "is_notification_enabled": 1,
    "post_enabled": 0,
    "app_enabled": 0,
    "blocker_enabled": 0,
    "approval_pending_enabled": 0,
    "meeting_enabled": 0,
    "task_enabled": 0,
    "mention_enabled": 0,
    "reply_enabled": 0,
    "chat_enabled": 0,
    "friend_enabled": 0,
}


def test_save_email_settings_invalid_routine_returns_400(mock_db, regular_user):
    client = _make_client(mock_db)
    payload = dict(EMAIL_SAVE_PAYLOAD, routine=999)
    with _auth(regular_user, target=PATCH_TARGET_EMAIL):
        resp = client.post("/api/v1/notifications/emailnotifysettings/save", json=payload)
    assert resp.status_code == 400
    assert "Invalid routine value" in resp.json()["detail"]


def test_save_email_settings_user_not_found_returns_404(mock_db, regular_user):
    mock_db.execute = AsyncMock(return_value=_FakeResult(scalar_one_or_none=None))
    client = _make_client(mock_db)
    with _auth(regular_user, target=PATCH_TARGET_EMAIL):
        resp = client.post("/api/v1/notifications/emailnotifysettings/save", json=EMAIL_SAVE_PAYLOAD)
    assert resp.status_code == 404


def test_save_email_settings_creates_new(mock_db, regular_user):
    target_user = _mk_user()
    mock_db.execute = AsyncMock(
        side_effect=[
            _FakeResult(scalar_one_or_none=target_user),
            _FakeResult(scalar_one_or_none=None),
        ]
    )
    client = _make_client(mock_db)
    with _auth(regular_user, target=PATCH_TARGET_EMAIL):
        resp = client.post("/api/v1/notifications/emailnotifysettings/save", json=EMAIL_SAVE_PAYLOAD)
    assert resp.status_code == 200
    mock_db.add.assert_called_once()


# ---------------------------------------------------------------------------
# PUT /emailnotifysettings/update
# ---------------------------------------------------------------------------

EMAIL_UPDATE_PAYLOAD = dict(EMAIL_SAVE_PAYLOAD, id=VALID_NOTIF_ID)


def test_update_email_settings_invalid_routine_returns_400(mock_db, regular_user):
    client = _make_client(mock_db)
    payload = dict(EMAIL_UPDATE_PAYLOAD, routine=13)
    with _auth(regular_user, target=PATCH_TARGET_EMAIL):
        resp = client.put("/api/v1/notifications/emailnotifysettings/update", json=payload)
    assert resp.status_code == 400


def test_update_email_settings_not_found_returns_404(mock_db, regular_user):
    mock_db.execute = AsyncMock(return_value=_FakeResult(scalar_one_or_none=None))
    client = _make_client(mock_db)
    with _auth(regular_user, target=PATCH_TARGET_EMAIL):
        resp = client.put("/api/v1/notifications/emailnotifysettings/update", json=EMAIL_UPDATE_PAYLOAD)
    assert resp.status_code == 404


def test_update_email_settings_success(mock_db, regular_user):
    notification = MagicMock()
    notification.id = VALID_NOTIF_ID
    notification.resource_id = VALID_USER_ID
    notification.created_by = "user-001"
    notification.updated_by = "user-001"
    notification.created_time = None
    notification.updated_time = None
    notification.last_email_notify_time = None
    mock_db.execute = AsyncMock(return_value=_FakeResult(scalar_one_or_none=notification))
    client = _make_client(mock_db)
    with _auth(regular_user, target=PATCH_TARGET_EMAIL):
        resp = client.put("/api/v1/notifications/emailnotifysettings/update", json=EMAIL_UPDATE_PAYLOAD)
    assert resp.status_code == 200
    assert mock_db.commit.await_count == 1


# ---------------------------------------------------------------------------
# GET /emailnotifysettings/{userId}
# ---------------------------------------------------------------------------

def test_get_email_settings_invalid_uuid_returns_400(mock_db, regular_user):
    client = _make_client(mock_db)
    with _auth(regular_user, target=PATCH_TARGET_EMAIL):
        resp = client.get("/api/v1/notifications/emailnotifysettings/not-a-uuid")
    assert resp.status_code == 400


def test_get_email_settings_user_not_found_returns_404(mock_db, regular_user):
    mock_db.execute = AsyncMock(return_value=_FakeResult(scalar_one_or_none=None))
    client = _make_client(mock_db)
    with _auth(regular_user, target=PATCH_TARGET_EMAIL):
        resp = client.get(f"/api/v1/notifications/emailnotifysettings/{VALID_USER_ID}")
    assert resp.status_code == 404


def test_get_email_settings_missing_returns_defaults(mock_db, regular_user):
    target_user = _mk_user()
    mock_db.execute = AsyncMock(
        side_effect=[
            _FakeResult(scalar_one_or_none=target_user),
            _FakeResult(scalar_one_or_none=None),
        ]
    )
    client = _make_client(mock_db)
    with _auth(regular_user, target=PATCH_TARGET_EMAIL):
        resp = client.get(f"/api/v1/notifications/emailnotifysettings/{VALID_USER_ID}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] is None
    assert body["is_notification_enabled"] == 0
    assert body["resource_id"] == VALID_USER_ID


# ---------------------------------------------------------------------------
# POST /emailnotifysettings/test/trigger
# ---------------------------------------------------------------------------

def test_trigger_scheduler_not_running_returns_503(mock_db, regular_user):
    fake_scheduler = MagicMock()
    fake_scheduler.is_running = False
    with _auth(regular_user, target=PATCH_TARGET_EMAIL), patch(
        "app.services.daily_summary_scheduler.daily_summary_scheduler", fake_scheduler
    ):
        client = _make_client(mock_db)
        resp = client.post("/api/v1/notifications/emailnotifysettings/test/trigger")
    assert resp.status_code == 503
    assert "Scheduler is not running" in resp.json()["detail"]


def test_trigger_scheduler_success(mock_db, regular_user):
    fake_scheduler = MagicMock()
    fake_scheduler.is_running = True
    fake_scheduler.process_daily_summaries = AsyncMock()
    with _auth(regular_user, target=PATCH_TARGET_EMAIL), patch(
        "app.services.daily_summary_scheduler.daily_summary_scheduler", fake_scheduler
    ):
        client = _make_client(mock_db)
        resp = client.post("/api/v1/notifications/emailnotifysettings/test/trigger")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    fake_scheduler.process_daily_summaries.assert_awaited_once()


def test_trigger_scheduler_anonymous_when_auth_raises(mock_db):
    """Characterizes the bare `except:` around the auth call: any exception
    (including one raised by get_current_user_required itself) falls back
    to 'Triggered anonymously' rather than propagating as an error."""
    fake_scheduler = MagicMock()
    fake_scheduler.is_running = True
    fake_scheduler.process_daily_summaries = AsyncMock()
    with patch(PATCH_TARGET_EMAIL, new=AsyncMock(side_effect=RuntimeError("no auth"))), patch(
        "app.services.daily_summary_scheduler.daily_summary_scheduler", fake_scheduler
    ):
        client = _make_client(mock_db)
        resp = client.post("/api/v1/notifications/emailnotifysettings/test/trigger")
    assert resp.status_code == 200
    assert resp.json()["triggered_by"] == "Triggered anonymously"
