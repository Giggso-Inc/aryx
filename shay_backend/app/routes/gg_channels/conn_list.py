"""GET /{channel_id}/app-connections  list_channel_app_connections

Split from the original connections.py (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Wave B4).
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.gg_app_connections import GGAppConnection
from app.models.user import User
from app.schemas.gg_channels import GGChannelAppConnectionList

from .helpers import _conn_resp, _get_channel_or_404, _to_uuid

router = APIRouter()


@router.get("/{channel_id}/app-connections", response_model=GGChannelAppConnectionList)
async def list_channel_app_connections(
    channel_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    app_id:    Optional[str]  = None,
    is_active: Optional[bool] = None,
) -> GGChannelAppConnectionList:
    """List all GGAppConnections for a channel (level='channel')."""
    await get_current_user_required(request, db)

    ch_uuid = _to_uuid(channel_id, "channel_id")
    await _get_channel_or_404(db, ch_uuid)

    filters = [
        GGAppConnection.channel_id == ch_uuid,
        GGAppConnection.level      == "channel",
    ]
    if app_id:
        filters.append(GGAppConnection.app_id == app_id)
    if is_active is not None:
        filters.append(GGAppConnection.is_active == is_active)

    base_q = select(GGAppConnection).where(and_(*filters))
    total = (await db.execute(select(func.count()).select_from(base_q.subquery()))).scalar()
    rows = (await db.execute(
        base_q.order_by(GGAppConnection.created_at.desc()).offset((page - 1) * size).limit(size)
    )).scalars().all()

    connector_ids = [r.connected_by for r in rows]
    users_by_id = {
        u.id: u for u in (
            await db.execute(select(User).where(User.id.in_(connector_ids)))
        ).scalars().all()
    } if connector_ids else {}

    return GGChannelAppConnectionList(
        connections=[_conn_resp(r, users_by_id.get(r.connected_by)) for r in rows],
        total=total,
        page=page,
        size=size,
        pages=(total + size - 1) // size,
    )
