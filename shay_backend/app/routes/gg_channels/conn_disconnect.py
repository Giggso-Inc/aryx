"""DELETE /{channel_id}/app-connections/{connection_id}  disconnect_channel_app

Split from the original connections.py (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Wave B4).
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.gg_app_connections import GGAppConnection

from .helpers import _get_channel_or_404, _to_uuid

router = APIRouter()


@router.delete("/{channel_id}/app-connections/{connection_id}", status_code=200)
async def disconnect_channel_app(
    channel_id:    str,
    connection_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Remove a GGAppConnection from a channel."""
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

    await db.delete(conn)
    await db.commit()
    return {"message": "App connection removed from channel successfully"}
