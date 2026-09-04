"""
Scope-listing gg_app_connections endpoint (static two-segment path, so it
has no collision with detail.py's single-segment /{connection_id} regardless
of registration order):
  GET /scope/{scope_type}/{scope_id}   list_connections_by_scope
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.gg_app_connections import GGAppConnection
from app.models.user import User
from app.schemas.gg_app_connections import GGAppConnectionList

from ._shared import assert_member_access, assert_scope_exists, build_response

router = APIRouter()


@router.get("/scope/{scope_type}/{scope_id}", response_model=GGAppConnectionList)
async def list_connections_by_scope(
    scope_type: str,
    scope_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    app_id: Optional[str] = None,
    is_active: Optional[bool] = None,
) -> GGAppConnectionList:
    """
    List all GGAppConnections for a specific workspace, channel, or thread scope.
    scope_type: 'workspace' | 'channel' | 'thread'
    """
    user = await get_current_user_required(request, db)

    if scope_type not in ("workspace", "channel", "thread"):
        raise HTTPException(status_code=400, detail="scope_type must be workspace, channel, or thread")

    try:
        scope_uuid = UUID(scope_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid scope_id format")

    # Validate scope exists and check access
    company_id = await assert_scope_exists(
        db,
        scope_type,
        workspace_id=scope_uuid if scope_type == "workspace" else None,
        channel_id=scope_uuid   if scope_type == "channel"   else None,
        thread_id=scope_uuid    if scope_type == "thread"    else None,
    )
    await assert_member_access(
        db,
        user_id=user.id,
        level=scope_type,
        workspace_id=scope_uuid if scope_type == "workspace" else None,
        channel_id=scope_uuid   if scope_type == "channel"   else None,
        thread_id=scope_uuid    if scope_type == "thread"    else None,
        user_company_id=str(user.company_id),
        company_id_from_scope=company_id,
    )

    scope_filter = {
        "workspace": and_(GGAppConnection.level == "workspace", GGAppConnection.workspace_id == scope_uuid),
        "channel":   and_(GGAppConnection.level == "channel",   GGAppConnection.channel_id   == scope_uuid),
        "thread":    and_(GGAppConnection.level == "thread",    GGAppConnection.thread_id    == scope_uuid),
    }

    filters = [scope_filter[scope_type]]
    if app_id:
        filters.append(GGAppConnection.app_id == app_id)
    if is_active is not None:
        filters.append(GGAppConnection.is_active == is_active)

    base_query = select(GGAppConnection).where(and_(*filters))

    total = (await db.execute(
        select(func.count()).select_from(base_query.subquery())
    )).scalar()

    rows = (await db.execute(
        base_query.order_by(GGAppConnection.created_at.desc())
                  .offset((page - 1) * size)
                  .limit(size)
    )).scalars().all()

    connector_ids = [r.connected_by for r in rows]
    users_by_id = {
        u.id: u for u in (
            await db.execute(select(User).where(User.id.in_(connector_ids)))
        ).scalars().all()
    } if connector_ids else {}

    return GGAppConnectionList(
        connections=[build_response(r, users_by_id.get(r.connected_by)) for r in rows],
        total=total,
        page=page,
        size=size,
        pages=(total + size - 1) // size,
    )
