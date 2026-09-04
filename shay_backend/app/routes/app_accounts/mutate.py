"""
PUT /{app_account_id} — update_app_account.

Split out of the original app/routes/app_accounts.py (755 lines) as part of
the Raven style-compliance file-splitting pass (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2).
"""

from __future__ import annotations

import copy

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.app import App
from app.models.app_account import AppAccount
from app.models.channel import Channel
from app.models.user import User
from app.schemas.app_account import AppAccountResponse, AppAccountUpdate

from .helpers import build_app_account_response, build_sharepoint_credentials_metadata, handle_app_account_vault_integration

router = APIRouter()


@router.put("/{app_account_id}", response_model=AppAccountResponse)
async def update_app_account(
    app_account_id: str,
    app_account_data: AppAccountUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> AppAccountResponse:
    """Update an app account"""
    user = await get_current_user_required(request, db)

    # Get app account with channel company_id to avoid lazy loading
    app_account_stmt = select(AppAccount, Channel.company_id).join(Channel).where(AppAccount.id == app_account_id)
    app_account_result = await db.execute(app_account_stmt)
    app_account_row = app_account_result.first()

    if not app_account_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="App account not found"
        )

    app_account, channel_company_id = app_account_row

    # Check if user has access to this connection
    if channel_company_id != user.company_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to this app account"
        )

    # Get app to check if it's SharePoint
    app_stmt = select(App).where(App.id == app_account.app_id)
    app_result = await db.execute(app_stmt)
    app = app_result.scalar_one_or_none()

    # Update app account fields
    update_data = app_account_data.dict(exclude_unset=True)

    # Process connection_settings - append Client ID and Secret for Jira if being updated
    if "connection_settings" in update_data:
        connection_settings = update_data["connection_settings"]
        if connection_settings and isinstance(connection_settings, dict):
            # Create a copy to avoid modifying the original
            connection_settings = copy.deepcopy(connection_settings)
            provider = connection_settings.get("provider")
            if provider == "jira":
                connection_settings["client_id"] = settings.JIRA_CLIENT_ID
                connection_settings["client_secret"] = settings.JIRA_CLIENT_SECRET

            # Handle vault integration for SharePoint credentials if being updated
            if app and app.app_key and app.app_key.lower() in ['sharepoint', 'share_point']:
                # Build SharePoint credentials metadata for vault
                credentials_metadata = build_sharepoint_credentials_metadata(connection_settings)

                if credentials_metadata:
                    try:
                        vault_result = await handle_app_account_vault_integration(
                            credentials_metadata=credentials_metadata,
                            user_id=str(user.id),
                            company_id=str(channel_company_id),
                            db=db,
                            required=True
                        )
                        if vault_result:
                            # Remove sensitive credentials from connection_settings
                            sanitized_settings = {
                                "provider": connection_settings.get("provider"),
                                "oauth_provider": connection_settings.get("oauth_provider"),
                                "connection_method": connection_settings.get("connection_method"),
                                "email_id": connection_settings.get("email_id"),
                                "scope": connection_settings.get("scope")
                            }
                            update_data["connection_settings"] = sanitized_settings
                    except HTTPException as e:
                        raise e
                    except Exception as e:
                        raise HTTPException(
                            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail=f"Failed to integrate with vault service: {str(e)}"
                        )
            else:
                update_data["connection_settings"] = connection_settings

    for field, value in update_data.items():
        setattr(app_account, field, value)

    await db.commit()
    await db.refresh(app_account)

    # Load connected user for user_metadata
    connected_user_stmt = select(User).where(User.id == app_account.connected_by)
    connected_user_result = await db.execute(connected_user_stmt)
    connected_user = connected_user_result.scalar_one_or_none()

    return build_app_account_response(app_account, connected_user)
