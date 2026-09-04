"""
POST / — create_app_account.

Split out of the original app/routes/app_accounts.py (755 lines) as part of
the Raven style-compliance file-splitting pass (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2).
"""

from __future__ import annotations

import copy
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.app import App
from app.models.app_account import AppAccount
from app.models.channel import Channel
from app.schemas.app_account import AppAccountCreate, AppAccountResponse

from .helpers import build_app_account_response, build_sharepoint_credentials_metadata, handle_app_account_vault_integration

router = APIRouter()


@router.post("/", response_model=AppAccountResponse)
async def create_app_account(
    app_account_data: AppAccountCreate,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> AppAccountResponse:
    """Create a new app account connection"""
    user = await get_current_user_required(request, db)

    # Verify app exists and is active
    app_stmt = select(App).where(
        and_(
            App.id == app_account_data.app_id,
            App.is_active == True
        )
    )
    app_result = await db.execute(app_stmt)
    app = app_result.scalar_one_or_none()

    if not app:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="App not found or not active"
        )

    # Verify channel exists and user has access
    channel_stmt = select(Channel).where(Channel.id == app_account_data.channel_id)
    channel_result = await db.execute(channel_stmt)
    channel = channel_result.scalar_one_or_none()

    if not channel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Channel not found"
        )

    if not channel.is_accessible_by_user(user.company_id, user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to this channel"
        )

    # Check if connection already exists
    existing_connection_stmt = select(AppAccount).where(
        and_(
            AppAccount.app_id == app_account_data.app_id,
            AppAccount.channel_id == app_account_data.channel_id,
            AppAccount.is_active == True
        )
    )
    existing_connection_result = await db.execute(existing_connection_stmt)
    existing_connection = existing_connection_result.scalar_one_or_none()

    if existing_connection:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="App is already connected to this channel"
        )

    # Process connection_settings - append Client ID and Secret for Jira
    connection_settings = app_account_data.connection_settings
    if connection_settings and isinstance(connection_settings, dict):
        # Create a copy to avoid modifying the original
        connection_settings = copy.deepcopy(connection_settings)
        provider = connection_settings.get("provider")
        if provider == "jira":
            connection_settings["client_id"] = settings.JIRA_CLIENT_ID
            connection_settings["client_secret"] = settings.JIRA_CLIENT_SECRET

    # Handle vault integration for SharePoint credentials
    if app.app_key and app.app_key.lower() in ['sharepoint', 'share_point']:
        if connection_settings and isinstance(connection_settings, dict):
            # Build SharePoint credentials metadata for vault
            credentials_metadata = build_sharepoint_credentials_metadata(connection_settings)

            if credentials_metadata:
                try:
                    vault_result = await handle_app_account_vault_integration(
                        credentials_metadata=credentials_metadata,
                        user_id=str(user.id),
                        company_id=str(channel.company_id),
                        db=db,
                        required=True
                    )
                    if vault_result:
                        # Remove sensitive credentials from connection_settings (keep only non-sensitive metadata)
                        sanitized_settings = {
                            "provider": connection_settings.get("provider"),
                            "oauth_provider": connection_settings.get("oauth_provider"),
                            "connection_method": connection_settings.get("connection_method"),
                            "email_id": connection_settings.get("email_id"),
                            "scope": connection_settings.get("scope")
                        }
                        connection_settings = sanitized_settings
                except HTTPException as e:
                    raise e
                except Exception as e:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=f"Failed to integrate with vault service: {str(e)}"
                    )

    # Create app account
    app_account = AppAccount(
        id=str(uuid.uuid4()),
        app_id=app_account_data.app_id,
        channel_id=app_account_data.channel_id,
        connected_by=user.id,
        connection_name=app_account_data.connection_name,
        connection_status=app_account_data.connection_status,
        connection_settings=connection_settings,
        webhook_url=app_account_data.webhook_url,
        callback_url=app_account_data.callback_url,
        is_active=app_account_data.is_active,
        auto_sync=app_account_data.auto_sync,
        sync_interval=app_account_data.sync_interval
    )

    db.add(app_account)
    await db.commit()
    await db.refresh(app_account)

    # Include user_metadata (email_id, name, user_id, avatar_url) for the user who created the connection
    return build_app_account_response(app_account, user)
