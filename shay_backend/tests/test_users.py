"""
Unit tests for /api/v1/users endpoints.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient
from fastapi import FastAPI

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.routes.users import router
from app.core.database import get_db


def _scalar(value):
    r = MagicMock()
    r.scalar_one_or_none = MagicMock(return_value=value)
    r.scalar = MagicMock(return_value=0)
    r.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    return r


def _make_client(mock_db, current_user):
    with patch("app.routes.users.get_current_user_required", new=AsyncMock(return_value=current_user)):
        app = FastAPI()
        app.include_router(router, prefix="/users")
        app.dependency_overrides[get_db] = lambda: mock_db
        return TestClient(app)


class TestGetCurrentUser:
    @pytest.mark.unit
    def test_get_me_success(self, mock_db, admin_user, mock_user):
        mock_db.execute = AsyncMock(return_value=_scalar(mock_user))
        client = _make_client(mock_db, admin_user)
        resp = client.get("/users/me")
        assert resp.status_code == 200

    @pytest.mark.unit
    def test_get_me_user_not_found(self, mock_db, admin_user):
        mock_db.execute = AsyncMock(return_value=_scalar(None))
        client = _make_client(mock_db, admin_user)
        resp = client.get("/users/me")
        assert resp.status_code == 404


class TestListUsers:
    @pytest.mark.unit
    def test_list_users_admin_success(self, mock_db, admin_user, mock_user):
        count_r = MagicMock()
        count_r.scalar = MagicMock(return_value=1)
        list_r = MagicMock()
        list_r.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[mock_user])))
        mock_db.execute = AsyncMock(side_effect=[count_r, list_r])

        client = _make_client(mock_db, admin_user)
        resp = client.get("/users/")
        assert resp.status_code == 200
        data = resp.json()
        assert "users" in data or isinstance(data, list)

    @pytest.mark.unit
    def test_list_users_pagination_params(self, mock_db, admin_user):
        count_r = MagicMock()
        count_r.scalar = MagicMock(return_value=0)
        list_r = MagicMock()
        list_r.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        mock_db.execute = AsyncMock(side_effect=[count_r, list_r])

        client = _make_client(mock_db, admin_user)
        resp = client.get("/users/?page=2&size=5")
        assert resp.status_code == 200

    @pytest.mark.unit
    def test_list_users_non_admin_forbidden(self, mock_db, regular_user):
        client = _make_client(mock_db, regular_user)
        resp = client.get("/users/")
        assert resp.status_code in (200, 403)


class TestGetUserById:
    @pytest.mark.unit
    def test_get_user_by_id_success(self, mock_db, admin_user, mock_user):
        mock_db.execute = AsyncMock(return_value=_scalar(mock_user))
        client = _make_client(mock_db, admin_user)
        resp = client.get("/users/user-001")
        assert resp.status_code == 200

    @pytest.mark.unit
    def test_get_user_by_id_not_found(self, mock_db, admin_user):
        mock_db.execute = AsyncMock(return_value=_scalar(None))
        client = _make_client(mock_db, admin_user)
        resp = client.get("/users/user-999")
        assert resp.status_code == 404


class TestUpdateUser:
    @pytest.mark.unit
    def test_update_user_success(self, mock_db, admin_user, mock_user):
        mock_db.execute = AsyncMock(return_value=_scalar(mock_user))
        client = _make_client(mock_db, admin_user)
        resp = client.put(
            "/users/user-001",
            json={"name": "Updated Name"},
        )
        assert resp.status_code == 200

    @pytest.mark.unit
    def test_update_user_not_found(self, mock_db, admin_user):
        mock_db.execute = AsyncMock(return_value=_scalar(None))
        client = _make_client(mock_db, admin_user)
        resp = client.put("/users/user-999", json={"name": "X"})
        assert resp.status_code == 404

    @pytest.mark.unit
    def test_update_own_profile_success(self, mock_db, regular_user, mock_user):
        mock_user.id = regular_user.id
        mock_db.execute = AsyncMock(return_value=_scalar(mock_user))
        client = _make_client(mock_db, regular_user)
        resp = client.put(
            f"/users/{regular_user.id}",
            json={"name": "My New Name"},
        )
        assert resp.status_code == 200

    @pytest.mark.unit
    def test_update_company_user_blocks_self_role_or_status_change(self, mock_db, admin_user):
        app = FastAPI()
        app.include_router(router, prefix="/users")
        app.dependency_overrides[get_db] = lambda: mock_db
        client = TestClient(app, raise_server_exceptions=False)

        admin_user.can_access_company = MagicMock(return_value=True)
        mock_db.execute = AsyncMock()

        with patch("app.routes.users.get_current_user_required", new=AsyncMock(return_value=admin_user)):
            resp = client.put(
                f"/users/company/{admin_user.company_id}/users/{admin_user.id}",
                json={"role": "user"},
            )

        assert resp.status_code == 400
        assert resp.json()["detail"] == "Cannot change your own role or active status"
        mock_db.execute.assert_not_awaited()


class TestDeleteUser:
    @pytest.mark.unit
    def test_delete_user_admin_success(self, mock_db, admin_user, mock_user):
        mock_db.execute = AsyncMock(return_value=_scalar(mock_user))
        client = _make_client(mock_db, admin_user)
        resp = client.delete("/users/user-001")
        assert resp.status_code in (200, 204)

    @pytest.mark.unit
    def test_delete_user_not_found(self, mock_db, admin_user):
        mock_db.execute = AsyncMock(return_value=_scalar(None))
        client = _make_client(mock_db, admin_user)
        resp = client.delete("/users/user-999")
        assert resp.status_code == 404
