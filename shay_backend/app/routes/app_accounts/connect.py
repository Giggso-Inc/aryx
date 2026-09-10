"""
POST /connect — connect_app_to_channel.

Split out of the original app/routes/app_accounts.py (755 lines) as part of
the Raven style-compliance file-splitting pass (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.app import App
from app.models.app_account import AppAccount
from app.models.channel import Channel
from app.schemas.app_account import AppAccountResponse, AppConnectionRequest

from .connection_settings import resolve_create_connection_settings
from .helpers import build_app_account_response

router = APIRouter()


@router.post("/connect", response_model=AppAccountResponse)
async def connect_app_to_channel(
    connection_data: AppConnectionRequest,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> AppAccountResponse:
    """Connect an app to a channel"""
    user = await get_current_user_required(request, db)

    # Verify app exists and is active
    app_stmt = select(App).where(
        and_(
            App.id == connection_data.app_id,
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
    channel_stmt = select(Channel).where(Channel.id == connection_data.channel_id)
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
            AppAccount.app_id == connection_data.app_id,
            AppAccount.channel_id == connection_data.channel_id,
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

    # Process connection_settings: inject Jira client credentials, and for
    # SharePoint apps push credentials to the vault and sanitize the settings.
    connection_settings = await resolve_create_connection_settings(
        app_key=app.app_key,
        connection_settings=connection_data.connection_settings,
        user_id=str(user.id),
        company_id=str(channel.company_id),
        db=db,
    )

    # Create app account
    app_account = AppAccount(
        id=str(uuid.uuid4()),
        app_id=connection_data.app_id,
        channel_id=connection_data.channel_id,
        connected_by=user.id,
        connection_name=connection_data.connection_name,
        connection_status="active",
        connection_settings=connection_settings,
        webhook_url=connection_data.webhook_url,
        callback_url=connection_data.callback_url,
        is_active=True,
        auto_sync=connection_data.auto_sync,
        sync_interval=connection_data.sync_interval
    )

    db.add(app_account)
    await db.commit()
    await db.refresh(app_account)

    # Include user_metadata (email_id, name, user_id, avatar_url) for the user who connected
    return build_app_account_response(app_account, user)
