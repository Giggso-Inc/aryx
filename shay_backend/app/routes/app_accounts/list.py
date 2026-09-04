"""
GET / — list_app_accounts.

Split out of the original app/routes/app_accounts.py (755 lines) as part of
the Raven style-compliance file-splitting pass (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2).
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.app import App
from app.models.app_account import AppAccount
from app.models.channel import Channel
from app.models.user import User
from app.schemas.app_account import AppAccountList

from .helpers import build_app_account_response

router = APIRouter()


@router.get("/", response_model=AppAccountList)
async def list_app_accounts(
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    app_id: Optional[str] = None,
    channel_id: Optional[str] = None,
    connection_status: Optional[str] = None,
    is_active: Optional[bool] = None
) -> AppAccountList:
    """List app accounts with filtering and pagination"""
    user = await get_current_user_required(request, db)

    # Build query with joins including User for user_metadata (email_id, name, user_id, avatar_url)
    query = select(AppAccount, User).join(App).join(Channel).join(User, AppAccount.connected_by == User.id)

    # Apply filters
    filters = []

    # Filter by user's company channels
    filters.append(Channel.company_id == user.company_id)

    if app_id:
        filters.append(AppAccount.app_id == app_id)

    if channel_id:
        filters.append(AppAccount.channel_id == channel_id)

    if connection_status:
        filters.append(AppAccount.connection_status == connection_status)

    if is_active is not None:
        filters.append(AppAccount.is_active == is_active)

    # Apply filters to query
    if filters:
        query = query.where(and_(*filters))

    # Get total count (from same filter set, without User join for count)
    count_query = select(func.count()).select_from(query.subquery())
    count_result = await db.execute(count_query)
    total = count_result.scalar()

    # Apply pagination
    offset = (page - 1) * size
    query = query.offset(offset).limit(size)

    # Execute query; each row is (AppAccount, User)
    result = await db.execute(query)
    rows = result.all()

    # Calculate pagination info
    pages = (total + size - 1) // size

    return AppAccountList(
        app_accounts=[build_app_account_response(account, connected_user) for account, connected_user in rows],
        total=total,
        page=page,
        size=size,
        pages=pages
    )
