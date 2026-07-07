"""
Regression tests for re-inviting users who were soft-removed from a company.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.database import get_db
from app.core.encryption_utils import create_registration_url
from app.routes.user_auth import router


def _scalar_result(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _make_client(mock_db):
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/user-auth")
    app.dependency_overrides[get_db] = lambda: mock_db
    return TestClient(app, raise_server_exceptions=False)


def test_bulk_invite_allows_inactive_existing_user(mock_db, mock_company):
    existing_user = MagicMock()
    existing_user.is_active = False
    existing_user.email_id = "shay@giggso.com"

    mock_db.execute = AsyncMock(
        side_effect=[
            _scalar_result(mock_company),
            _scalar_result(existing_user),
        ]
    )

    client = _make_client(mock_db)
    with patch("app.routes.user_auth.link_shortener_service.shorten", new=AsyncMock(return_value="short-link")), \
         patch("app.routes.user_auth.email_service.send_invitation_email", return_value=True):
        response = client.post(
            "/api/v1/user-auth/bulk-invite",
            json={
                "users": [
                    {
                        "email": "shay@giggso.com",
                        "company_id": "company-001",
                        "role": "user",
                    }
                ],
                "platform_name": "Aryx",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_invited"] == 1
    assert payload["failed_invitations"] == []


def test_register_reactivates_inactive_existing_user_with_invite(mock_db, mock_company):
    existing_user = MagicMock()
    existing_user.id = "user-removed-001"
    existing_user.email_id = "shay@giggso.com"
    existing_user.name = "Old Name"
    existing_user.company_id = None
    existing_user.role = "user"
    existing_user.is_active = False
    existing_user.is_verified = False
    existing_user.avatar_url = None

    invitation = MagicMock()
    invitation.id = "invite-001"
    invitation.email = "shay@giggso.com"
    invitation.company_id = "company-001"
    invitation.role = "admin"
    invitation.status = "pending"
    invitation.is_valid = True
    invitation.updated_at = None

    workspace = MagicMock()
    workspace.id = "workspace-001"
    workspace.name = "Test Company"
    workspace.company_id = "company-001"

    mock_db.execute = AsyncMock(
        side_effect=[
            _scalar_result(existing_user),
            _scalar_result(invitation),
            _scalar_result(mock_company),
            _scalar_result(workspace),
        ]
    )
    mock_db.refresh = AsyncMock()

    client = _make_client(mock_db)
    with patch("app.routes.user_auth.get_password_hash", return_value="hashed-password"), \
         patch("app.routes.user_auth.ensure_workspace_membership", new=AsyncMock()), \
         patch("app.routes.user_auth.create_access_token", return_value="access-token"), \
         patch("app.routes.user_auth.create_refresh_token", return_value="refresh-token"):
        response = client.post(
            "/api/v1/user-auth/register",
            json={
                "invite_id": "invite-001",
                "email_id": "shay@giggso.com",
                "password": "ValidPass123!",
                "name": "Shay",
                "encrypted": False,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["user_id"] == "user-removed-001"
    assert payload["email_id"] == "shay@giggso.com"
    assert existing_user.is_active is True
    assert existing_user.company_id == "company-001"


def test_decrypt_registration_invite_returns_prefill_data():
    client = _make_client(AsyncMock())
    registration_url = create_registration_url(
        "https://aryx.example.com",
        "shay@giggso.com",
        "invite-001",
        "company-001",
        "user",
    )
    encrypted_param = registration_url.split("?e=", 1)[1]

    response = client.get(
        "/api/v1/user-auth/decrypt-registration",
        params={"e": encrypted_param},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["email_id"] == "shay@giggso.com"
    assert payload["invite_id"] == "invite-001"
    assert payload["company_id"] == "company-001"
    assert payload["role"] == "user"
