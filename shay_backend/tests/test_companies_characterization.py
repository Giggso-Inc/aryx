"""
Golden-master / characterization tests for app/routes/companies.py.

Purpose: tests/test_companies.py exercises get_my_company, get_company,
list_companies, update_company, invite_user, and get_company_stats, but
leaves three endpoints with ZERO coverage (confirmed by reading
tests/test_companies.py in full: no reference to "/test", "/invitations",
or "/invitations/{id}/accept" anywhere in that file):

  - GET  /test                                  (test_models)
  - GET  /{company_id}/invitations               (list_invitations)
  - POST /invitations/{invitation_id}/accept    (accept_invitation)

companies.py is about to be split into a package (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2). Before the
split, this file captures the CURRENT observable behavior of those three
endpoints so the split can be verified to change nothing.

These are characterization tests, not "correctness" tests: assertions match
what the code actually does today, bugs included.

Pattern follows tests/test_channels_characterization.py:
- FastAPI TestClient with `app.include_router(router, prefix=...)`.
- `app.dependency_overrides[get_db] = lambda: mock_db`.
- MagicMock/AsyncMock for services; no real DB, no real HTTP.
- `asyncio.run()` is not needed here since TestClient drives the async
  endpoints synchronously, same as tests/test_companies.py.

Do not modify app/routes/companies (the package) from this file's tests.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routes.companies import router
from app.core.database import get_db


def _scalar_result(value):
    """Return a mock whose .scalar_one_or_none() returns `value`."""
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=value)
    result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    result.scalar = MagicMock(return_value=0)
    return result


def _client(mock_db):
    app = FastAPI()
    app.include_router(router, prefix="/companies")
    app.dependency_overrides[get_db] = lambda: mock_db
    return TestClient(app)


# ---------------------------------------------------------------------------
# GET /companies/test  (list_company.test_models) — no auth required
# ---------------------------------------------------------------------------
class TestModelsEndpoint:
    @pytest.mark.unit
    def test_models_success(self, mock_db):
        """Happy path: the three lazily-imported models import cleanly."""
        resp = _client(mock_db).get("/companies/test")
        assert resp.status_code == 200
        data = resp.json()
        assert data == {"status": "success", "message": "Models imported successfully"}


# ---------------------------------------------------------------------------
# GET /companies/{company_id}/invitations  (invitations.list_invitations)
# ---------------------------------------------------------------------------
class TestListInvitations:
    @pytest.mark.unit
    def test_list_invitations_success_empty(self, mock_db, admin_user):
        """Happy path: admin lists invitations for their own company, none exist."""
        count_result = MagicMock()
        count_result.scalar = MagicMock(return_value=0)

        data_result = MagicMock()
        data_result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))

        users_result = MagicMock()
        users_result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))

        mock_db.execute = AsyncMock(side_effect=[count_result, data_result, users_result])

        with patch(
            "app.routes.companies.invitations.get_current_user_required",
            new=AsyncMock(return_value=admin_user),
        ):
            resp = _client(mock_db).get("/companies/company-001/invitations")

        assert resp.status_code == 200
        body = resp.json()
        assert body["invitations"] == []
        assert body["total"] == 0
        assert body["total_pages"] == 0
        assert body["has_next"] is False
        assert body["has_previous"] is False

    @pytest.mark.unit
    def test_list_invitations_forbidden_for_other_company(self, mock_db, regular_user):
        """Access denied: non-admin from a different company than the path."""
        regular_user.company_id = "company-OTHER"

        with patch(
            "app.routes.companies.invitations.get_current_user_required",
            new=AsyncMock(return_value=regular_user),
        ):
            resp = _client(mock_db).get("/companies/company-001/invitations")

        assert resp.status_code == 403
        assert resp.json()["detail"] == "Access denied"

    @pytest.mark.unit
    def test_list_invitations_invalid_sort_by(self, mock_db, admin_user):
        """Current behavior: an invalid sort_by is only rejected AFTER the
        (redundant) total count query has already executed once — the
        endpoint calls db.execute for the count query before validating
        sort_by, so the mock must supply that one execute() result even
        though the response is a 400."""
        count_result = MagicMock()
        count_result.scalar = MagicMock(return_value=0)
        mock_db.execute = AsyncMock(return_value=count_result)

        with patch(
            "app.routes.companies.invitations.get_current_user_required",
            new=AsyncMock(return_value=admin_user),
        ):
            resp = _client(mock_db).get(
                "/companies/company-001/invitations?sort_by=bogus"
            )

        assert resp.status_code == 400
        assert "Invalid sort_by field" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# POST /companies/invitations/{invitation_id}/accept  (accept.accept_invitation)
# ---------------------------------------------------------------------------
class TestAcceptInvitation:
    @pytest.mark.unit
    def test_accept_invitation_success(self, mock_db, mock_invitation):
        mock_invitation.is_valid = True
        side_effects = [
            _scalar_result(mock_invitation),  # invitation lookup
            _scalar_result(None),             # no existing user with that email
        ]
        mock_db.execute = AsyncMock(side_effect=side_effects)

        resp = _client(mock_db).post(
            "/companies/invitations/inv-001/accept",
            json={"invitation_id": "inv-001", "name": "New User"},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["message"] == "Invitation accepted successfully"
        assert "user_id" in body

    @pytest.mark.unit
    def test_accept_invitation_not_found(self, mock_db):
        mock_db.execute = AsyncMock(return_value=_scalar_result(None))

        resp = _client(mock_db).post(
            "/companies/invitations/does-not-exist/accept",
            json={"invitation_id": "does-not-exist", "name": "New User"},
        )

        assert resp.status_code == 404
        assert resp.json()["detail"] == "Invitation not found"

    @pytest.mark.unit
    def test_accept_invitation_expired_or_invalid(self, mock_db, mock_invitation):
        mock_invitation.is_valid = False
        mock_db.execute = AsyncMock(return_value=_scalar_result(mock_invitation))

        resp = _client(mock_db).post(
            "/companies/invitations/inv-001/accept",
            json={"invitation_id": "inv-001", "name": "New User"},
        )

        assert resp.status_code == 400
        assert "not valid or has expired" in resp.json()["detail"]

    @pytest.mark.unit
    def test_accept_invitation_user_already_exists(self, mock_db, mock_invitation, mock_user):
        mock_invitation.is_valid = True
        side_effects = [
            _scalar_result(mock_invitation),  # invitation lookup
            _scalar_result(mock_user),        # existing user with that email
        ]
        mock_db.execute = AsyncMock(side_effect=side_effects)

        resp = _client(mock_db).post(
            "/companies/invitations/inv-001/accept",
            json={"invitation_id": "inv-001", "name": "New User"},
        )

        assert resp.status_code == 400
        assert "already exists" in resp.json()["detail"]
