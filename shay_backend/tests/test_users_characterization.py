"""
Golden-master / characterization tests for app/routes/users.py (gap-fill).

Purpose: tests/test_users.py exists but, on close reading, exercises paths
that do not match ANY route this router actually defines: GET /users/me,
GET /users/, GET|PUT|DELETE /users/{id} (top-level, no /company/ prefix).
This router's 8 real endpoints are all nested under
/company/{company_id}/... (plus a top-level /search). Confirmed by grep:
none of "/me", '"/"', or a bare "/{user_id}" path decorator exists in
app/routes/users.py (now app/routes/users/*.py); running test_users.py
against the real router shows 8 of its 13 tests already fail at baseline
(asserting 200 where the real response is 404) -- those are dead tests
against nonexistent routes, not real coverage. The only test in
test_users.py that exercises a real, existing route is
TestUpdateUser::test_update_company_user_blocks_self_role_or_status_change
(PUT /company/{company_id}/users/{user_id}), and only its "cannot change
your own role" 400 branch.

So all 8 real endpoints -- list_company_users, get_company_user,
update_company_user (minus the one branch above), remove_company_user,
get_company_user_stats, search_users_by_name_or_email,
delete_pending_invited_user, bulk_remove_company_users -- had effectively
ZERO real test coverage before this file. It is about to be split into a
package (see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item
2). This file captures the CURRENT observable behavior of those endpoints
so the split can be verified to change nothing.

Pattern follows tests/test_channels_characterization.py:
- FastAPI TestClient with `app.include_router(router, prefix=...)`.
- `app.dependency_overrides[get_db] = lambda: mock_db`.
- MagicMock/AsyncMock for services; no real DB, no real HTTP.

Do not modify app/routes/users.py (now app/routes/users/) from this file's
tests.
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
    from app.routes.users import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/users")
    app.dependency_overrides[get_db] = lambda: mock_db
    return TestClient(app, raise_server_exceptions=False)


def _auth(user, module):
    """Patch get_current_user_required on the specific submodule that owns
    the endpoint under test (each submodule imports it directly) -- see the
    CRITICAL GOTCHA in the compliance plan: patching
    app.routes.users.get_current_user_required would NOT affect a
    submodule's own bound reference. search.py does not import
    get_current_user_required at all (see TestSearchUsers)."""
    return patch(f"app.routes.users.{module}.get_current_user_required", new=AsyncMock(return_value=user))


def _uid():
    return str(uuid.uuid4())


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
        return m

    def scalar(self):
        return self._scalar_val


def _exec_seq(*results):
    return AsyncMock(side_effect=list(results))


def _mock_user_row(**overrides):
    u = MagicMock()
    u.id = _uid()
    u.name = "Target User"
    u.email_id = "target@example.com"
    u.avatar_url = None
    u.company_id = "company-001"
    u.role = "user"
    u.is_active = True
    u.last_login = None
    u.created_datetime = datetime.utcnow()
    u.updated_datetime = datetime.utcnow()
    for k, v in overrides.items():
        setattr(u, k, v)
    return u


def _mock_company(**overrides):
    c = MagicMock()
    c.id = "company-001"
    c.subscription_plan = "pro"
    for k, v in overrides.items():
        setattr(c, k, v)
    return c


def _grant_company_access(user, allowed=True):
    user.can_access_company = MagicMock(return_value=allowed)
    return user


# ===========================================================================
# GET /company/{company_id}/users — list_company_users
# ===========================================================================

class TestListCompanyUsers:
    """Characterization of a real pre-existing bug: list_company_users
    declares a Query parameter named `status` (`status: Optional[str] =
    Query(...)`), which shadows the module-level `from fastapi import
    ... status` import for the rest of the function body. Every
    `raise HTTPException(status_code=status.HTTP_xxx, ...)` in this endpoint
    -- the access-denied 403, the invalid sort_by 400, the invalid
    sort_order 400, and the invalid status-value 400 -- therefore raises
    AttributeError instead (since the local `status` is None or a string,
    not the fastapi module), which FastAPI's default exception handler
    turns into a bare 500. Only the happy path (which never reaches a
    `status.HTTP_xxx` reference) is unaffected. Documented as-is, not
    fixed."""

    def test_access_denied_hits_status_shadowing_bug_500(self, mock_db, regular_user):
        _grant_company_access(regular_user, False)
        client = _make_client(mock_db)
        with _auth(regular_user, "list_users"):
            resp = client.get(f"/api/v1/users/company/{_uid()}/users", headers={"Authorization": "Bearer t"})
        assert resp.status_code == 500

    def test_invalid_sort_by_hits_status_shadowing_bug_500(self, mock_db, admin_user):
        _grant_company_access(admin_user, True)
        client = _make_client(mock_db)
        with _auth(admin_user, "list_users"):
            resp = client.get(f"/api/v1/users/company/{_uid()}/users?sort_by=bogus", headers={"Authorization": "Bearer t"})
        assert resp.status_code == 500

    def test_invalid_status_value_hits_status_shadowing_bug_500(self, mock_db, admin_user):
        _grant_company_access(admin_user, True)
        client = _make_client(mock_db)
        with _auth(admin_user, "list_users"):
            resp = client.get(f"/api/v1/users/company/{_uid()}/users?status=bogus", headers={"Authorization": "Bearer t"})
        assert resp.status_code == 500

    def test_happy_path_no_pagination(self, mock_db, admin_user):
        _grant_company_access(admin_user, True)
        row = _mock_user_row()
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_val=1),   # total
            _FakeResult(scalar_val=1),   # total_active
            _FakeResult(scalar_val=0),   # total_inactive
            _FakeResult(scalar_val=0),   # total_admin
            _FakeResult(all_=[row]),     # data query (no pagination branch)
        )
        client = _make_client(mock_db)
        with _auth(admin_user, "list_users"):
            resp = client.get(f"/api/v1/users/company/{_uid()}/users", headers={"Authorization": "Bearer t"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["page"] == 1
        assert body["has_next"] is False
        assert len(body["users"]) == 1

    def test_happy_path_with_pagination(self, mock_db, admin_user):
        _grant_company_access(admin_user, True)
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_val=25),  # total
            _FakeResult(scalar_val=20),  # total_active
            _FakeResult(scalar_val=5),   # total_inactive
            _FakeResult(scalar_val=2),   # total_admin
            _FakeResult(all_=[]),        # data query (paginated branch)
        )
        client = _make_client(mock_db)
        with _auth(admin_user, "list_users"):
            resp = client.get(f"/api/v1/users/company/{_uid()}/users?page=1&size=10", headers={"Authorization": "Bearer t"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_pages"] == 3
        assert body["has_next"] is True
        assert body["has_previous"] is False


# ===========================================================================
# GET /company/{company_id}/users/{user_id} — get_company_user
# ===========================================================================

class TestGetCompanyUser:
    def test_access_denied_403(self, mock_db, regular_user):
        _grant_company_access(regular_user, False)
        client = _make_client(mock_db)
        with _auth(regular_user, "detail"):
            resp = client.get(f"/api/v1/users/company/{_uid()}/users/{_uid()}", headers={"Authorization": "Bearer t"})
        assert resp.status_code == 403

    def test_not_found_404(self, mock_db, admin_user):
        _grant_company_access(admin_user, True)
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        client = _make_client(mock_db)
        with _auth(admin_user, "detail"):
            resp = client.get(f"/api/v1/users/company/{_uid()}/users/{_uid()}", headers={"Authorization": "Bearer t"})
        assert resp.status_code == 404

    def test_happy_path(self, mock_db, admin_user):
        _grant_company_access(admin_user, True)
        row = _mock_user_row()
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=row))
        client = _make_client(mock_db)
        with _auth(admin_user, "detail"):
            resp = client.get(f"/api/v1/users/company/{_uid()}/users/{row.id}", headers={"Authorization": "Bearer t"})
        assert resp.status_code == 200
        assert resp.json()["id"] == str(row.id)


# ===========================================================================
# PUT /company/{company_id}/users/{user_id} — update_company_user
# (only the branches NOT already covered by tests/test_users.py)
# ===========================================================================

class TestUpdateCompanyUser:
    def test_access_denied_403(self, mock_db, regular_user):
        _grant_company_access(regular_user, False)
        client = _make_client(mock_db)
        with _auth(regular_user, "detail"):
            resp = client.put(
                f"/api/v1/users/company/{_uid()}/users/{_uid()}",
                json={"name": "x"},
                headers={"Authorization": "Bearer t"},
            )
        assert resp.status_code == 403

    def test_insufficient_permission_403(self, mock_db, regular_user):
        _grant_company_access(regular_user, True)
        regular_user.role = "user"
        client = _make_client(mock_db)
        with _auth(regular_user, "detail"):
            resp = client.put(
                f"/api/v1/users/company/{_uid()}/users/{_uid()}",
                json={"name": "x"},
                headers={"Authorization": "Bearer t"},
            )
        assert resp.status_code == 403
        assert "Insufficient permissions" in resp.json()["detail"]

    def test_not_found_404(self, mock_db, admin_user):
        _grant_company_access(admin_user, True)
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        client = _make_client(mock_db)
        with _auth(admin_user, "detail"):
            resp = client.put(
                f"/api/v1/users/company/{_uid()}/users/{_uid()}",
                json={"name": "x"},
                headers={"Authorization": "Bearer t"},
            )
        assert resp.status_code == 404

    def test_non_admin_cannot_assign_admin_role_403(self, mock_db, regular_user):
        """Characterization: current_user.role is checked against ["admin",
        "manager"] first (passes for a manager), then a second check blocks
        assigning role=admin unless the actor is already an admin."""
        _grant_company_access(regular_user, True)
        regular_user.role = "manager"
        row = _mock_user_row()
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=row))
        client = _make_client(mock_db)
        with _auth(regular_user, "detail"):
            resp = client.put(
                f"/api/v1/users/company/{_uid()}/users/{row.id}",
                json={"role": "admin"},
                headers={"Authorization": "Bearer t"},
            )
        assert resp.status_code == 403
        assert "Only admins can assign admin role" in resp.json()["detail"]

    def test_happy_path_field_update(self, mock_db, admin_user):
        _grant_company_access(admin_user, True)
        row = _mock_user_row(name="old-name")
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=row))
        client = _make_client(mock_db)
        with _auth(admin_user, "detail"):
            resp = client.put(
                f"/api/v1/users/company/{_uid()}/users/{row.id}",
                json={"name": "new-name"},
                headers={"Authorization": "Bearer t"},
            )
        assert resp.status_code == 200
        assert row.name == "new-name"
        assert resp.json()["name"] == "new-name"


# ===========================================================================
# DELETE /company/{company_id}/users/{user_id} — remove_company_user
# ===========================================================================

class TestRemoveCompanyUser:
    def test_non_admin_403(self, mock_db, regular_user):
        regular_user.company_id = "company-001"
        client = _make_client(mock_db)
        with _auth(regular_user, "detail"):
            resp = client.delete(
                "/api/v1/users/company/company-001/users/some-user",
                headers={"Authorization": "Bearer t"},
            )
        assert resp.status_code == 403

    def test_self_removal_blocked_400(self, mock_db, admin_user):
        admin_user.company_id = "company-001"
        client = _make_client(mock_db)
        with _auth(admin_user, "detail"):
            resp = client.delete(
                f"/api/v1/users/company/company-001/users/{admin_user.id}",
                headers={"Authorization": "Bearer t"},
            )
        assert resp.status_code == 400
        assert "Cannot remove yourself" in resp.json()["detail"]

    def test_not_found_404(self, mock_db, admin_user):
        admin_user.company_id = "company-001"
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        client = _make_client(mock_db)
        with _auth(admin_user, "detail"):
            resp = client.delete(
                "/api/v1/users/company/company-001/users/other-user",
                headers={"Authorization": "Bearer t"},
            )
        assert resp.status_code == 404

    def test_happy_path_deactivates_and_revokes_memberships(self, mock_db, admin_user):
        admin_user.company_id = "company-001"
        row = _mock_user_row(id="other-user", is_active=True, company_id="company-001")
        membership = MagicMock(is_active=True, updated_at=None)
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=row),
            _FakeResult(all_=[membership]),
        )
        client = _make_client(mock_db)
        with _auth(admin_user, "detail"):
            resp = client.delete(
                "/api/v1/users/company/company-001/users/other-user",
                headers={"Authorization": "Bearer t"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["revoked_channel_memberships"] == 1
        assert row.is_active is False
        assert row.company_id is None
        assert membership.is_active is False


# ===========================================================================
# GET /company/{company_id}/stats — get_company_user_stats
# ===========================================================================

class TestGetCompanyUserStats:
    def test_access_denied_403(self, mock_db, regular_user):
        regular_user.company_id = "other-company"
        regular_user.role = "user"
        client = _make_client(mock_db)
        with _auth(regular_user, "stats"):
            resp = client.get("/api/v1/users/company/company-001/stats", headers={"Authorization": "Bearer t"})
        assert resp.status_code == 403

    def test_company_not_found_404(self, mock_db, admin_user):
        admin_user.company_id = "company-001"
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        client = _make_client(mock_db)
        with _auth(admin_user, "stats"):
            resp = client.get("/api/v1/users/company/company-001/stats", headers={"Authorization": "Bearer t"})
        assert resp.status_code == 404

    def test_happy_path(self, mock_db, admin_user):
        admin_user.company_id = "company-001"
        company = _mock_company()
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=company),
            _FakeResult(scalar_val=5),   # active users
            _FakeResult(scalar_val=2),   # workspaces
            _FakeResult(scalar_val=10),  # messages
            _FakeResult(scalar_val=3),   # attachments
        )
        client = _make_client(mock_db)
        with _auth(admin_user, "stats"):
            resp = client.get("/api/v1/users/company/company-001/stats", headers={"Authorization": "Bearer t"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_users"] == 5
        assert body["subscription_plan"] == "pro"

    def test_stats_query_error_falls_back_to_zeros(self, mock_db, admin_user):
        """Characterization: get_company_user_stats wraps its four count
        queries in try/except Exception and silently returns zeros on any
        failure, rather than propagating the error."""
        admin_user.company_id = "company-001"
        company = _mock_company()
        mock_db.execute = AsyncMock(side_effect=[_FakeResult(scalar_one_or_none=company), RuntimeError("boom")])
        client = _make_client(mock_db)
        with _auth(admin_user, "stats"):
            resp = client.get("/api/v1/users/company/company-001/stats", headers={"Authorization": "Bearer t"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_users"] == 0
        assert body["total_workspaces"] == 0


# ===========================================================================
# GET /search — search_users_by_name_or_email
# ===========================================================================

class TestSearchUsers:
    def test_no_params_400(self, mock_db):
        client = _make_client(mock_db)
        resp = client.get("/api/v1/users/search")
        assert resp.status_code == 400

    def test_happy_path_by_name(self, mock_db):
        row = _mock_user_row()
        mock_db.execute = _exec_seq(_FakeResult(all_=[row]))
        client = _make_client(mock_db)
        resp = client.get("/api/v1/users/search?name=Target")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        assert body[0]["email_id"] == row.email_id


# ===========================================================================
# DELETE /company/{company_id}/pendingInvitedUsers/{email_id} —
# delete_pending_invited_user
# ===========================================================================

class TestDeletePendingInvitedUser:
    def test_non_admin_403(self, mock_db, regular_user):
        client = _make_client(mock_db)
        with _auth(regular_user, "invitations"):
            resp = client.delete(
                "/api/v1/users/company/company-001/pendingInvitedUsers/x@example.com",
                headers={"Authorization": "Bearer t"},
            )
        assert resp.status_code == 403

    def test_access_denied_to_company_403(self, mock_db, admin_user):
        _grant_company_access(admin_user, False)
        client = _make_client(mock_db)
        with _auth(admin_user, "invitations"):
            resp = client.delete(
                "/api/v1/users/company/company-001/pendingInvitedUsers/x@example.com",
                headers={"Authorization": "Bearer t"},
            )
        assert resp.status_code == 403
        assert "Access denied to this company" in resp.json()["detail"]

    def test_no_pending_invitations_404(self, mock_db, admin_user):
        _grant_company_access(admin_user, True)
        mock_db.execute = _exec_seq(_FakeResult(all_=[]))
        client = _make_client(mock_db)
        with _auth(admin_user, "invitations"):
            resp = client.delete(
                "/api/v1/users/company/company-001/pendingInvitedUsers/x@example.com",
                headers={"Authorization": "Bearer t"},
            )
        assert resp.status_code == 404

    def test_happy_path(self, mock_db, admin_user):
        _grant_company_access(admin_user, True)
        inv1 = MagicMock()
        inv2 = MagicMock()
        mock_db.execute = _exec_seq(_FakeResult(all_=[inv1, inv2]))
        client = _make_client(mock_db)
        with _auth(admin_user, "invitations"):
            resp = client.delete(
                "/api/v1/users/company/company-001/pendingInvitedUsers/x@example.com",
                headers={"Authorization": "Bearer t"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["deleted_count"] == 2
        assert mock_db.delete.await_count == 2


# ===========================================================================
# DELETE /company/{company_id}/users — bulk_remove_company_users
# ===========================================================================

class TestBulkRemoveCompanyUsers:
    def test_non_admin_403(self, mock_db, regular_user):
        client = _make_client(mock_db)
        with _auth(regular_user, "bulk"):
            resp = client.request(
                "DELETE",
                f"/api/v1/users/company/{uuid.uuid4()}/users",
                json={"user_ids": [str(uuid.uuid4())]},
                headers={"Authorization": "Bearer t"},
            )
        assert resp.status_code == 403

    def test_cross_company_403(self, mock_db, admin_user):
        admin_user.company_id = "11111111-1111-1111-1111-111111111111"
        client = _make_client(mock_db)
        with _auth(admin_user, "bulk"):
            resp = client.request(
                "DELETE",
                f"/api/v1/users/company/{uuid.uuid4()}/users",
                json={"user_ids": [str(uuid.uuid4())]},
                headers={"Authorization": "Bearer t"},
            )
        assert resp.status_code == 403

    def test_self_removal_blocked_400(self, mock_db, admin_user):
        company_id = str(uuid.uuid4())
        admin_user.company_id = company_id
        admin_user.id = str(uuid.uuid4())
        client = _make_client(mock_db)
        with _auth(admin_user, "bulk"):
            resp = client.request(
                "DELETE",
                f"/api/v1/users/company/{company_id}/users",
                json={"user_ids": [str(admin_user.id)]},
                headers={"Authorization": "Bearer t"},
            )
        assert resp.status_code == 400
        assert "Cannot remove yourself" in resp.json()["detail"]

    def test_no_users_found_404(self, mock_db, admin_user):
        company_id = str(uuid.uuid4())
        admin_user.company_id = company_id
        admin_user.id = str(uuid.uuid4())
        mock_db.execute = _exec_seq(_FakeResult(all_=[]))
        client = _make_client(mock_db)
        with _auth(admin_user, "bulk"):
            resp = client.request(
                "DELETE",
                f"/api/v1/users/company/{company_id}/users",
                json={"user_ids": [str(uuid.uuid4())]},
                headers={"Authorization": "Bearer t"},
            )
        assert resp.status_code == 404

    def test_happy_path(self, mock_db, admin_user):
        company_id = str(uuid.uuid4())
        admin_user.company_id = company_id
        admin_user.id = str(uuid.uuid4())
        target_id = uuid.uuid4()
        row = _mock_user_row(id=target_id)
        membership = MagicMock(is_active=True, updated_at=None)
        mock_db.execute = _exec_seq(
            _FakeResult(all_=[row]),
            _FakeResult(all_=[membership]),
        )
        client = _make_client(mock_db)
        with _auth(admin_user, "bulk"):
            resp = client.request(
                "DELETE",
                f"/api/v1/users/company/{company_id}/users",
                json={"user_ids": [str(target_id)]},
                headers={"Authorization": "Bearer t"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["removed_user_ids"] == [str(target_id)]
        assert row.is_active is False
        assert membership.is_active is False

    def test_commit_failure_500(self, mock_db, admin_user):
        """Characterization: on a commit failure, the endpoint rolls back
        and returns a generic 500 with a fixed message (not the raw
        exception text)."""
        company_id = str(uuid.uuid4())
        admin_user.company_id = company_id
        admin_user.id = str(uuid.uuid4())
        target_id = uuid.uuid4()
        row = _mock_user_row(id=target_id)
        mock_db.execute = _exec_seq(
            _FakeResult(all_=[row]),
            _FakeResult(all_=[]),
        )
        mock_db.commit = AsyncMock(side_effect=RuntimeError("db down"))
        client = _make_client(mock_db)
        with _auth(admin_user, "bulk"):
            resp = client.request(
                "DELETE",
                f"/api/v1/users/company/{company_id}/users",
                json={"user_ids": [str(target_id)]},
                headers={"Authorization": "Bearer t"},
            )
        assert resp.status_code == 500
        assert resp.json()["detail"] == "Failed to remove users"
        mock_db.rollback.assert_awaited()
