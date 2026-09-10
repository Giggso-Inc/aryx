"""
Response-building helpers for the app_accounts route package.

Split out of the original app_accounts/helpers.py (Raven style-compliance
pass, see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Wave B4).
"""

from __future__ import annotations

from typing import Optional

from app.models.app_account import AppAccount
from app.models.user import User
from app.schemas.app_account import AppAccountResponse, UserMetadata


def build_user_metadata(user: Optional[User]) -> Optional[UserMetadata]:
    """Build user_metadata (email_id, name, user_id, avatar_url) from User for app account response."""
    if not user:
        return None
    return UserMetadata(
        email_id=user.email_id,
        name=user.name,
        user_id=str(user.id),
        avatar_url=user.avatar_url
    )


def build_app_account_response(account: AppAccount, connected_user: Optional[User] = None) -> AppAccountResponse:
    """Build AppAccountResponse with optional user_metadata from the connected user."""
    return AppAccountResponse(
        id=str(account.id),
        app_id=str(account.app_id),
        channel_id=str(account.channel_id),
        connection_name=account.connection_name,
        connection_status=account.connection_status,
        connection_settings=account.connection_settings,
        webhook_url=account.webhook_url,
        callback_url=account.callback_url,
        is_active=account.is_active,
        auto_sync=account.auto_sync,
        sync_interval=account.sync_interval,
        connected_by=str(account.connected_by),
        user_metadata=build_user_metadata(connected_user),
        last_sync_at=account.last_sync_at,
        sync_status=account.sync_status,
        error_message=account.error_message,
        created_at=account.created_at,
        updated_at=account.updated_at
    )
