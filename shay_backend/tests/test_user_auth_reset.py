"""
Unit tests for password reset token enforcement.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _scalar_result(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
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
