"""
Unit tests for /api/v1/companies endpoints.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient
from fastapi import FastAPI

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.routes.companies import router
from app.core.database import get_db


# ---------------------------------------------------------------------------
# Minimal app for this test module
# ---------------------------------------------------------------------------
def _make_app(mock_db, current_user):
    app = FastAPI()
    app.include_router(router, prefix="/companies")
    app.dependency_overrides[get_db] = lambda: mock_db

    # patch auth at import level so all calls within the route use the mock
    patcher = patch(
        "app.routes.companies.get_current_user_required",
        new=AsyncMock(return_value=current_user),
    )
    patcher.start()
    yield app
    patcher.stop()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _scalar_result(value):
    """Return a mock whose .scalar_one_or_none() returns `value`."""
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=value)
    result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    result.scalar = MagicMock(return_value=0)
    return result


# ---------------------------------------------------------------------------
# Tests: GET /companies/my
# ---------------------------------------------------------------------------
class TestGetMyCompany:
    @pytest.fixture(autouse=True)
    def setup(self, mock_db, admin_user, mock_company):
        self.mock_db = mock_db
        self.admin_user = admin_user
        self.mock_company = mock_company

    @pytest.mark.unit
    def test_get_my_company_success(self):
        self.admin_user.company_id = "company-001"
        self.mock_db.execute = AsyncMock(return_value=_scalar_result(self.mock_company))

        with patch("app.routes.companies.get_current_user_required", new=AsyncMock(return_value=self.admin_user)):
            app = FastAPI()
            app.include_router(router, prefix="/companies")
            app.dependency_overrides[get_db] = lambda: self.mock_db
            client = TestClient(app)
            resp = client.get("/companies/my")

        assert resp.status_code == 200

    @pytest.mark.unit
    def test_get_my_company_no_company(self):
        self.admin_user.company_id = None

        with patch("app.routes.companies.get_current_user_required", new=AsyncMock(return_value=self.admin_user)):
            app = FastAPI()
            app.include_router(router, prefix="/companies")
            app.dependency_overrides[get_db] = lambda: self.mock_db
            client = TestClient(app)
            resp = client.get("/companies/my")

        assert resp.status_code == 404
        assert "not associated" in resp.json()["detail"]

    @pytest.mark.unit
    def test_get_my_company_not_found_in_db(self):
        self.admin_user.company_id = "company-001"
        self.mock_db.execute = AsyncMock(return_value=_scalar_result(None))

        with patch("app.routes.companies.get_current_user_required", new=AsyncMock(return_value=self.admin_user)):
            app = FastAPI()
            app.include_router(router, prefix="/companies")
            app.dependency_overrides[get_db] = lambda: self.mock_db
            client = TestClient(app)
            resp = client.get("/companies/my")

        assert resp.status_code == 404
        assert "Company not found" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Tests: GET /companies/{company_id}
# ---------------------------------------------------------------------------
class TestGetCompanyById:
    @pytest.fixture(autouse=True)
    def setup(self, mock_db, admin_user, mock_company):
        self.mock_db = mock_db
        self.admin_user = admin_user
        self.mock_company = mock_company

    def _client(self, user=None):
        u = user or self.admin_user
        with patch("app.routes.companies.get_current_user_required", new=AsyncMock(return_value=u)):
            app = FastAPI()
            app.include_router(router, prefix="/companies")
            app.dependency_overrides[get_db] = lambda: self.mock_db
            return TestClient(app)

    @pytest.mark.unit
    def test_get_company_by_id_success(self):
        self.mock_db.execute = AsyncMock(return_value=_scalar_result(self.mock_company))
        resp = self._client().get("/companies/company-001")
        assert resp.status_code == 200

    @pytest.mark.unit
    def test_get_company_by_id_not_found(self):
        self.mock_db.execute = AsyncMock(return_value=_scalar_result(None))
        resp = self._client().get("/companies/company-001")
        assert resp.status_code == 404

    @pytest.mark.unit
    def test_get_company_by_id_forbidden_for_other_company(self, regular_user):
        regular_user.company_id = "company-OTHER"
        resp = self._client(user=regular_user).get("/companies/company-001")
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Tests: GET /companies/ (admin list)
# ---------------------------------------------------------------------------
class TestListCompanies:
    @pytest.fixture(autouse=True)
    def setup(self, mock_db, admin_user):
        self.mock_db = mock_db
        self.admin_user = admin_user

    def _client(self, user=None):
        u = user or self.admin_user
        with patch("app.routes.companies.get_current_user_required", new=AsyncMock(return_value=u)):
            app = FastAPI()
            app.include_router(router, prefix="/companies")
            app.dependency_overrides[get_db] = lambda: self.mock_db
            return TestClient(app)

    @pytest.mark.unit
    def test_list_companies_admin_success(self):
        mock_result_count = MagicMock()
        mock_result_count.scalar = MagicMock(return_value=0)
        mock_result_list = MagicMock()
        mock_result_list.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        self.mock_db.execute = AsyncMock(side_effect=[mock_result_count, mock_result_list])

        resp = self._client().get("/companies/")
        assert resp.status_code == 200
        data = resp.json()
        assert "companies" in data
        assert data["total"] == 0

    @pytest.mark.unit
    def test_list_companies_non_admin_forbidden(self, regular_user):
        resp = self._client(user=regular_user).get("/companies/")
        assert resp.status_code == 403

    @pytest.mark.unit
    def test_list_companies_with_pagination(self):
        mock_result_count = MagicMock()
        mock_result_count.scalar = MagicMock(return_value=5)
        mock_result_list = MagicMock()
        mock_result_list.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        self.mock_db.execute = AsyncMock(side_effect=[mock_result_count, mock_result_list])

        resp = self._client().get("/companies/?page=1&size=5")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Tests: PUT /companies/{company_id}
# ---------------------------------------------------------------------------
class TestUpdateCompany:
    @pytest.fixture(autouse=True)
    def setup(self, mock_db, admin_user, mock_company):
        self.mock_db = mock_db
        self.admin_user = admin_user
        self.mock_company = mock_company

    def _client(self, user=None):
        u = user or self.admin_user
        with patch("app.routes.companies.get_current_user_required", new=AsyncMock(return_value=u)):
            app = FastAPI()
            app.include_router(router, prefix="/companies")
            app.dependency_overrides[get_db] = lambda: self.mock_db
            return TestClient(app)

    @pytest.mark.unit
    def test_update_company_success(self):
        self.mock_db.execute = AsyncMock(return_value=_scalar_result(self.mock_company))
        resp = self._client().put(
            "/companies/company-001",
            json={"name": "Updated Name"},
        )
        assert resp.status_code == 200

    @pytest.mark.unit
    def test_update_company_not_found(self):
        self.mock_db.execute = AsyncMock(return_value=_scalar_result(None))
        resp = self._client().put(
            "/companies/company-001",
            json={"name": "X"},
        )
        assert resp.status_code == 404

    @pytest.mark.unit
    def test_update_company_forbidden(self, regular_user):
        regular_user.company_id = "company-OTHER"
        resp = self._client(user=regular_user).put(
            "/companies/company-001",
            json={"name": "X"},
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Tests: POST /companies/{company_id}/invite
# ---------------------------------------------------------------------------
class TestInviteUser:
    @pytest.fixture(autouse=True)
    def setup(self, mock_db, admin_user, mock_company, mock_invitation):
        self.mock_db = mock_db
        self.admin_user = admin_user
        self.mock_company = mock_company
        self.mock_invitation = mock_invitation

    def _client(self, user=None):
        u = user or self.admin_user
        with patch("app.routes.companies.get_current_user_required", new=AsyncMock(return_value=u)):
            app = FastAPI()
            app.include_router(router, prefix="/companies")
            app.dependency_overrides[get_db] = lambda: self.mock_db
            return TestClient(app)

    @pytest.mark.unit
    def test_invite_user_success(self):
        # company found, no existing user, no existing invitation
        side_effects = [
            _scalar_result(self.mock_company),  # get company
            _scalar_result(None),               # no existing user
            _scalar_result(None),               # no existing invitation
        ]
        self.mock_db.execute = AsyncMock(side_effect=side_effects)
        self.mock_db.refresh = AsyncMock()

        with patch("app.models.invitation.Invitation.create_invitation", return_value=self.mock_invitation):
            resp = self._client().post(
                "/companies/company-001/invite",
                json={"email": "newuser@example.com", "role": "user"},
            )
        assert resp.status_code == 200

    @pytest.mark.unit
    def test_invite_user_forbidden_different_company(self, regular_user):
        regular_user.company_id = "company-OTHER"
        resp = self._client(user=regular_user).post(
            "/companies/company-001/invite",
            json={"email": "x@example.com", "role": "user"},
        )
        assert resp.status_code == 403

    @pytest.mark.unit
    def test_invite_user_insufficient_role(self, regular_user):
        regular_user.company_id = "company-001"
        regular_user.role = "user"
        resp = self._client(user=regular_user).post(
            "/companies/company-001/invite",
            json={"email": "x@example.com", "role": "user"},
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Tests: GET /companies/{company_id}/stats
# ---------------------------------------------------------------------------
class TestGetCompanyStats:
    @pytest.fixture(autouse=True)
    def setup(self, mock_db, admin_user, mock_company):
        self.mock_db = mock_db
        self.admin_user = admin_user
        self.mock_company = mock_company

    @pytest.mark.unit
    def test_get_stats_success(self):
        def _scalar_n(n):
            r = MagicMock()
            r.scalar = MagicMock(return_value=n)
            return r

        self.mock_db.execute = AsyncMock(side_effect=[
            _scalar_result(self.mock_company),  # company lookup
            _scalar_n(10),   # user count
            _scalar_n(3),    # workspace count
            _scalar_n(50),   # message count
            _scalar_n(5),    # attachment count
        ])

        with patch("app.routes.companies.get_current_user_required", new=AsyncMock(return_value=self.admin_user)):
            app = FastAPI()
            app.include_router(router, prefix="/companies")
            app.dependency_overrides[get_db] = lambda: self.mock_db
            client = TestClient(app)
            resp = client.get("/companies/company-001/stats")

        assert resp.status_code == 200

    @pytest.mark.unit
    def test_get_stats_company_not_found(self):
        self.mock_db.execute = AsyncMock(return_value=_scalar_result(None))
        with patch("app.routes.companies.get_current_user_required", new=AsyncMock(return_value=self.admin_user)):
            app = FastAPI()
            app.include_router(router, prefix="/companies")
            app.dependency_overrides[get_db] = lambda: self.mock_db
            client = TestClient(app)
            resp = client.get("/companies/company-001/stats")
        assert resp.status_code == 404
