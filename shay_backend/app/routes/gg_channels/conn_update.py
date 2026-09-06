"""PUT /{channel_id}/app-connections/{connection_id}  update_channel_app_connection

Split from the original connections.py (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Wave B4).
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.gg_app_connections import GGAppConnection
from app.models.user import User
from app.schemas.gg_channels import GGChannelAppConnectionResponse, GGChannelAppConnectionUpdate

from .helpers import _conn_resp, _get_channel_or_404, _to_uuid

router = APIRouter()


@router.put("/{channel_id}/app-connections/{connection_id}", response_model=GGChannelAppConnectionResponse)
async def update_channel_app_connection(
    channel_id:    str,
    connection_id: str,
    data: GGChannelAppConnectionUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> GGChannelAppConnectionResponse:
    """Update a channel-level GGAppConnection."""
    user = await get_current_user_required(request, db)

    ch_uuid   = _to_uuid(channel_id,   "channel_id")
    conn_uuid = _to_uuid(connection_id, "connection_id")

    ch = await _get_channel_or_404(db, ch_uuid)
    if not ch.is_accessible_by_user(user.company_id, user.role):
        raise HTTPException(status_code=403, detail="Access denied to this channel")

    conn = (await db.execute(
        select(GGAppConnection).where(and_(
            GGAppConnection.id         == conn_uuid,
            GGAppConnection.channel_id == ch_uuid,
            GGAppConnection.level      == "channel",
        ))
    )).scalar_one_or_none()

    if not conn:
        raise HTTPException(status_code=404, detail="App connection not found for this channel")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(conn, field, value)

    await db.commit()
    await db.refresh(conn)

    connector = (await db.execute(select(User).where(User.id == conn.connected_by))).scalar_one_or_none()
    return _conn_resp(conn, connector)
