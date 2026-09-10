"""
GET /stats — get_app_account_stats.

Split out of the original app/routes/app_accounts.py (755 lines) as part of
the Raven style-compliance file-splitting pass (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2).

This is a literal path and MUST stay registered before the dynamic
GET /{app_account_id} in detail.py -- see __init__.py's route-order note.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.app_account import AppAccount
from app.models.channel import Channel
from app.models.user import User
from app.schemas.app_account import AppAccountStats

from .helpers import build_app_account_response

router = APIRouter()


@router.get("/stats", response_model=AppAccountStats)
async def get_app_account_stats(
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> AppAccountStats:
    """Get app account statistics"""
    user = await get_current_user_required(request, db)

    # Get total connections for user's company
    total_connections_query = select(func.count(AppAccount.id)).join(Channel).where(
        Channel.company_id == user.company_id
    )
    total_connections_result = await db.execute(total_connections_query)
    total_connections = total_connections_result.scalar()

    # Get active connections
    active_connections_query = select(func.count(AppAccount.id)).join(Channel).where(
        and_(
            Channel.company_id == user.company_id,
            AppAccount.is_active == True
        )
    )
    active_connections_result = await db.execute(active_connections_query)
    active_connections = active_connections_result.scalar()

    # Get error connections
    error_connections_query = select(func.count(AppAccount.id)).join(Channel).where(
        and_(
            Channel.company_id == user.company_id,
            AppAccount.connection_status == "error"
        )
    )
    error_connections_result = await db.execute(error_connections_query)
    error_connections = error_connections_result.scalar()

    # Get unique apps connected
    apps_connected_query = select(AppAccount.app_id).join(Channel).where(
        Channel.company_id == user.company_id
    ).distinct()
    apps_connected_result = await db.execute(apps_connected_query)
    apps_connected = [row[0] for row in apps_connected_result.fetchall()]

    # Get unique channels connected
    channels_connected_query = select(AppAccount.channel_id).join(Channel).where(
        Channel.company_id == user.company_id
    ).distinct()
    channels_connected_result = await db.execute(channels_connected_query)
    channels_connected = [row[0] for row in channels_connected_result.fetchall()]

    # Get recent connections
    recent_connections_query = select(AppAccount).join(Channel).where(
        Channel.company_id == user.company_id
    ).order_by(AppAccount.created_at.desc()).limit(5)
    recent_connections_result = await db.execute(recent_connections_query)
    recent_connections = recent_connections_result.scalars().all()

    # Load connected users for user_metadata (batch by ids)
    connected_by_ids = [acc.connected_by for acc in recent_connections]
    users_stmt = select(User).where(User.id.in_(connected_by_ids))
    users_result = await db.execute(users_stmt)
    users_by_id = {u.id: u for u in users_result.scalars().all()}

    return AppAccountStats(
        total_connections=total_connections,
        active_connections=active_connections,
        error_connections=error_connections,
        apps_connected=apps_connected,
        channels_connected=channels_connected,
        recent_connections=[build_app_account_response(account, users_by_id.get(account.connected_by)) for account in recent_connections]
    )
