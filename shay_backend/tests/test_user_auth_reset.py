"""
Unit tests for password reset token enforcement.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _scalar_result(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _first_result(value):
    result = MagicMock()
    result.first.return_value = value
    return result


def _make_client(mock_db):
    from app.core.database import get_db
    from app.routes.user_auth import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/user-auth")
    app.dependency_overrides[get_db] = lambda: mock_db
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.unit
def test_reset_password_requires_valid_password_reset_token(mock_db):
    mock_db.execute = AsyncMock(return_value=_scalar_result(None))
    client = _make_client(mock_db)

    response = client.post(
        "/api/v1/user-auth/reset-password",
        json={
            "token": "bad-token",
            "new_password": "ValidPass123!",
            "confirm_new_password": "ValidPass123!",
            "encrypted": False,
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid or expired password reset token"
    mock_db.commit.assert_not_awaited()


@pytest.mark.unit
def test_reset_password_marks_token_used_after_success(mock_db):
    token_record = MagicMock()
    token_record.token_type = "password_reset"
    token_record.is_valid = True
    token_record.user_id = "user-001"
    token_record.email = "user@example.com"

    user = MagicMock()
    user.id = "user-001"
    user.email_id = "user@example.com"
    user.is_active = True

    mock_db.execute = AsyncMock(
        side_effect=[
            _scalar_result(token_record),
            _scalar_result(user),
        ]
    )
    client = _make_client(mock_db)

    response = client.post(
        "/api/v1/user-auth/reset-password",
        json={
            "token": "good-token",
            "new_password": "ValidPass123!",
            "confirm_new_password": "ValidPass123!",
            "encrypted": False,
        },
    )

    assert response.status_code == 200
    assert response.json()["success"] is True
    token_record.mark_as_used.assert_called_once()
    mock_db.commit.assert_awaited_once()


@pytest.mark.unit
def test_reset_password_normalizes_whitespace_around_token(mock_db):
    token_record = MagicMock()
    token_record.token_type = "password_reset"
    token_record.is_valid = True
    token_record.user_id = "user-001"
    token_record.email = "user@example.com"

    user = MagicMock()
    user.id = "user-001"
    user.email_id = "user@example.com"
    user.is_active = True

    compiled_sql = []
    results = [
        _scalar_result(token_record),
        _scalar_result(user),
    ]

    def execute_side_effect(stmt, *args, **kwargs):
        compiled_sql.append(str(stmt.compile(compile_kwargs={"literal_binds": True})))
        return results.pop(0)

    mock_db.execute = AsyncMock(side_effect=execute_side_effect)
    client = _make_client(mock_db)

    response = client.post(
        "/api/v1/user-auth/reset-password",
        json={
            "token": "  good-token \n",
            "new_password": "ValidPass123!",
            "confirm_new_password": "ValidPass123!",
            "encrypted": False,
        },
    )

    assert response.status_code == 200
    assert "good-token" in compiled_sql[0]
    assert "  good-token " not in compiled_sql[0]


@pytest.mark.unit
def test_forgot_password_commits_token_before_shortening(mock_db):
    user = MagicMock()
    user.name = "Shay"
    user.email_id = "shay@example.com"
    user.company_id = "company-001"
    user.id = "user-001"
    user.is_active = True

    company = MagicMock()
    mock_db.execute = AsyncMock(return_value=_first_result((user, company)))

    client = _make_client(mock_db)

    async def shorten_side_effect(url, db=None):
        assert mock_db.commit.await_count == 1
        return url

    with patch("app.routes.user_auth.email_verification_service.invalidate_existing_tokens", new=AsyncMock(return_value=True)), \
         patch("app.routes.user_auth.link_shortener_service.shorten", new=AsyncMock(side_effect=shorten_side_effect)), \
         patch("app.routes.user_auth._send_default_password_reset_email", new=AsyncMock(return_value=True)):
        response = client.post(
            "/api/v1/user-auth/forgot-password",
            json={
                "email_id": "shay@example.com",
                "base_url": "http://localhost:3000",
                "app_name": "Aryx",
            },
        )

    assert response.status_code == 200
    assert response.json()["email_sent"] is True
    assert mock_db.commit.await_count >= 1
