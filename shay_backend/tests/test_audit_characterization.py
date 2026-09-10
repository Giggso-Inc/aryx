"""
Golden-master / characterization tests for app/routes/audit (package).

Purpose: audit.py was 389 lines with 3 endpoints and had ZERO test coverage
before this file (confirmed via grep across tests/ for "app.routes.audit").
It has been split into a package (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, wave B5):
  app/routes/audit/__init__.py  (router assembly)
  app/routes/audit/models.py    (AuditLogEntry, AuditLogListResponse)
  app/routes/audit/helpers.py   (_audit_query, _get_user_names,
                                  _get_related_user_ids_for_audit_rows,
                                  _collect_user_names_for_rows, _rows_to_items)
  app/routes/audit/list_all.py  (GET "" -> list_audit_log)
  app/routes/audit/channel.py   (GET /channel/{channel_id})
  app/routes/audit/thread.py    (GET /channel/{channel_id}/thread/{thread_id})

Because `get_current_user_required` is imported separately into each
endpoint submodule's own namespace, `unittest.mock.patch` targets it per
submodule (e.g. "app.routes.audit.list_all.get_current_user_required")
rather than the single "app.routes.audit.get_current_user_required" used
before the split. `_auth()` below takes the submodule as a parameter for
this reason.

These are characterization tests, not "correctness" tests: assertions match
what the code actually does today, bugs included. Notable current behavior
(not a bug, just asymmetric and worth documenting): `list_audit_log` (the
company-wide listing) silently drops an invalid `channel_id`/`thread_id`/
`user_id` query-string filter (try/except ValueError: pass) rather than
raising 400, whereas `list_channel_audit_log` and `list_thread_audit_log`
raise 400 for an invalid path-parameter UUID.

Pattern follows tests/test_checklists_characterization.py and
tests/test_subscriptions_characterization.py:
- FastAPI TestClient with `app.include_router(router, prefix=...)`.
- `app.dependency_overrides[get_db] = lambda: mock_db`.
- MagicMock/AsyncMock for the DB session; no real DB, no real HTTP.
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
    from app.routes.audit import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/audit")
    app.dependency_overrides[get_db] = lambda: mock_db
    return TestClient(app, raise_server_exceptions=False)


def _auth(user, module="app.routes.audit.list_all"):
    return patch(f"{module}.get_current_user_required", new=AsyncMock(return_value=user))


def _uid():
    return uuid.uuid4()


def _exec_result(scalar_one_or_none=None, scalar_val=None, all_=None):
    """Build a mock SQLAlchemy Result.

    Sets both `.scalars().all()` (used by the ORM-entity row queries, e.g. the
    main AuditLog listing) and `.all()` directly (used by `_get_user_names`
    and `_get_related_user_ids_for_audit_rows`, which select specific columns
    like `Task.id, Task.assigned_to` and therefore call `result.all()` without
    `.scalars()`). Without both, MagicMock's default `__iter__` silently
    returns an empty iterator for whichever accessor isn't explicitly set.
    """
    m = MagicMock()
    m.scalar_one_or_none = MagicMock(return_value=scalar_one_or_none)
    m.scalar = MagicMock(return_value=scalar_val)
    m.all = MagicMock(return_value=all_ if all_ is not None else [])
    scalars_mock = MagicMock()
    scalars_mock.all = MagicMock(return_value=all_ if all_ is not None else [])
    m.scalars = MagicMock(return_value=scalars_mock)
    return m


def _exec_seq(*results):
    return AsyncMock(side_effect=list(results))


def _mock_channel(company_id="company-001", accessible=True):
    ch = MagicMock()
    ch.id = _uid()
    ch.is_accessible_by_user = MagicMock(return_value=accessible)
    return ch


def _mock_user_row(user_id, name, email_id):
    r = MagicMock()
    r.id = user_id
    r.name = name
    r.email_id = email_id
    return r


def _mock_audit_row(
    resource_type="channel",
    action="channel.created",
    user_id=None,
    resource_id=None,
    channel_id=None,
    thread_id=None,
    details=None,
):
    r = MagicMock()
    r.id = _uid()
    r.user_id = user_id or _uid()
    r.action = action
    r.resource_type = resource_type
    r.resource_id = resource_id or _uid()
    r.channel_id = channel_id or _uid()
    r.thread_id = thread_id
    r.details = details
    r.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return r


# ---------------------------------------------------------------------------
# GET "" -> list_audit_log
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_list_audit_log_happy_path_empty(admin_user):
    mock_db = AsyncMock()
    mock_db.execute = _exec_seq(
        _exec_result(scalar_val=0),  # count
        _exec_result(all_=[]),  # rows
    )
    with _auth(admin_user):
        client = _make_client(mock_db)
        resp = client.get("/api/v1/audit")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"items": [], "total": 0, "page": 1, "size": 20}


@pytest.mark.unit
def test_list_audit_log_401_unauthenticated():
    mock_db = AsyncMock()
    from fastapi import HTTPException, status as http_status

    with patch(
        "app.routes.audit.list_all.get_current_user_required",
        new=AsyncMock(side_effect=HTTPException(status_code=http_status.HTTP_401_UNAUTHORIZED, detail="Authentication required")),
    ):
        client = _make_client(mock_db)
        resp = client.get("/api/v1/audit")
    assert resp.status_code == 401


@pytest.mark.unit
def test_list_audit_log_invalid_filter_uuids_silently_ignored(admin_user):
    """Current behavior: an invalid channel_id/thread_id/user_id query param is
    swallowed (try/except ValueError: pass) rather than raising 400 — the
    filter is simply not applied, unlike the path-param endpoints below."""
    mock_db = AsyncMock()
    mock_db.execute = _exec_seq(
        _exec_result(scalar_val=0),
        _exec_result(all_=[]),
    )
    with _auth(admin_user):
        client = _make_client(mock_db)
        resp = client.get(
            "/api/v1/audit",
            params={"channel_id": "not-a-uuid", "thread_id": "not-a-uuid", "user_id": "not-a-uuid"},
        )
    assert resp.status_code == 200


@pytest.mark.unit
def test_list_audit_log_with_task_row_resolves_related_user(admin_user):
    task_id = _uid()
    assignee_id = _uid()
    row = _mock_audit_row(resource_type="task", action="task.assigned", resource_id=task_id)
    task_row = MagicMock(id=task_id, assigned_to=assignee_id)
    mock_db = AsyncMock()
    mock_db.execute = _exec_seq(
        _exec_result(scalar_val=1),  # count
        _exec_result(all_=[row]),  # main rows
        _exec_result(all_=[task_row]),  # task assignee lookup
        _exec_result(all_=[_mock_user_row(row.user_id, "Actor", "a@x.com"),
                            _mock_user_row(assignee_id, "Assignee", "b@x.com")]),  # user names
    )
    with _auth(admin_user):
        client = _make_client(mock_db)
        resp = client.get("/api/v1/audit")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["related_user_name"] == "Assignee"
    assert item["user_name"] == "Actor"


# ---------------------------------------------------------------------------
# GET /channel/{channel_id} -> list_channel_audit_log
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_list_channel_audit_log_happy_path(admin_user):
    channel = _mock_channel(company_id=admin_user.company_id, accessible=True)
    mock_db = AsyncMock()
    mock_db.execute = _exec_seq(
        _exec_result(scalar_one_or_none=channel),  # channel lookup
        _exec_result(scalar_val=0),  # count
        _exec_result(all_=[]),  # rows
    )
    with _auth(admin_user, module="app.routes.audit.channel"):
        client = _make_client(mock_db)
        resp = client.get(f"/api/v1/audit/channel/{channel.id}")
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


@pytest.mark.unit
def test_list_channel_audit_log_invalid_uuid_400(admin_user):
    mock_db = AsyncMock()
    with _auth(admin_user, module="app.routes.audit.channel"):
        client = _make_client(mock_db)
        resp = client.get("/api/v1/audit/channel/not-a-uuid")
    assert resp.status_code == 400


@pytest.mark.unit
def test_list_channel_audit_log_404_when_channel_missing(admin_user):
    mock_db = AsyncMock()
    mock_db.execute = _exec_seq(_exec_result(scalar_one_or_none=None))
    with _auth(admin_user, module="app.routes.audit.channel"):
        client = _make_client(mock_db)
        resp = client.get(f"/api/v1/audit/channel/{_uid()}")
    assert resp.status_code == 404


@pytest.mark.unit
def test_list_channel_audit_log_403_access_denied(admin_user):
    channel = _mock_channel(company_id="some-other-company", accessible=False)
    mock_db = AsyncMock()
    mock_db.execute = _exec_seq(_exec_result(scalar_one_or_none=channel))
    with _auth(admin_user, module="app.routes.audit.channel"):
        client = _make_client(mock_db)
        resp = client.get(f"/api/v1/audit/channel/{channel.id}")
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# GET /channel/{channel_id}/thread/{thread_id} -> list_thread_audit_log
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_list_thread_audit_log_happy_path(admin_user):
    channel = _mock_channel(company_id=admin_user.company_id, accessible=True)
    mock_db = AsyncMock()
    mock_db.execute = _exec_seq(
        _exec_result(scalar_one_or_none=channel),
        _exec_result(scalar_val=0),
        _exec_result(all_=[]),
    )
    with _auth(admin_user, module="app.routes.audit.thread"):
        client = _make_client(mock_db)
        resp = client.get(f"/api/v1/audit/channel/{channel.id}/thread/{_uid()}")
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


@pytest.mark.unit
def test_list_thread_audit_log_invalid_uuid_400(admin_user):
    mock_db = AsyncMock()
    with _auth(admin_user, module="app.routes.audit.thread"):
        client = _make_client(mock_db)
        resp = client.get(f"/api/v1/audit/channel/{_uid()}/thread/not-a-uuid")
    assert resp.status_code == 400


@pytest.mark.unit
def test_list_thread_audit_log_404_when_channel_missing(admin_user):
    mock_db = AsyncMock()
    mock_db.execute = _exec_seq(_exec_result(scalar_one_or_none=None))
    with _auth(admin_user, module="app.routes.audit.thread"):
        client = _make_client(mock_db)
        resp = client.get(f"/api/v1/audit/channel/{_uid()}/thread/{_uid()}")
    assert resp.status_code == 404


@pytest.mark.unit
def test_list_thread_audit_log_403_access_denied(admin_user):
    channel = _mock_channel(company_id="some-other-company", accessible=False)
    mock_db = AsyncMock()
    mock_db.execute = _exec_seq(_exec_result(scalar_one_or_none=channel))
    with _auth(admin_user, module="app.routes.audit.thread"):
        client = _make_client(mock_db)
        resp = client.get(f"/api/v1/audit/channel/{channel.id}/thread/{_uid()}")
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Helper functions, exercised directly
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_rows_to_items_approval_reassigned_uses_new_approver_id():
    from app.routes.audit.helpers import _rows_to_items

    new_approver = str(_uid())
    row = _mock_audit_row(
        resource_type="approval",
        action="approval.reassigned",
        details={"new_approver_id": new_approver},
    )
    items = _rows_to_items([row], user_names={new_approver: "New Approver"}, related_maps={})
    assert items[0].related_user_id == new_approver
    assert items[0].related_user_name == "New Approver"


@pytest.mark.unit
def test_get_user_names_empty_list_short_circuits():
    from app.routes.audit.helpers import _get_user_names
    import asyncio

    mock_db = AsyncMock()
    result = asyncio.run(_get_user_names(mock_db, []))
    assert result == {}
    mock_db.execute.assert_not_called()
