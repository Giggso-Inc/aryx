"""POST /{channel_id}/app-connections  connect_channel_app

Split from the original connections.py (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Wave B4).
"""

from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.app import App
from app.models.gg_app_connections import GGAppConnection
from app.schemas.gg_channels import GGChannelAppConnectionCreate, GGChannelAppConnectionResponse

from .helpers import _conn_resp, _get_channel_or_404, _to_uuid

router = APIRouter()


@router.post("/{channel_id}/app-connections", response_model=GGChannelAppConnectionResponse, status_code=201)
async def connect_channel_app(
    channel_id: str,
    data: GGChannelAppConnectionCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> GGChannelAppConnectionResponse:
    """Connect an app to a channel via GGAppConnection (level='channel')."""
    user = await get_current_user_required(request, db)

    ch_uuid = _to_uuid(channel_id, "channel_id")
    ch = await _get_channel_or_404(db, ch_uuid)

    if not ch.is_accessible_by_user(user.company_id, user.role):
        raise HTTPException(status_code=403, detail="Access denied to this channel")

    app = (await db.execute(
        select(App).where(and_(App.id == data.app_id, App.is_active == True))
    )).scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="App not found or not active")

    existing = (await db.execute(
        select(GGAppConnection).where(and_(
            GGAppConnection.app_id     == data.app_id,
            GGAppConnection.channel_id == ch_uuid,
            GGAppConnection.level      == "channel",
            GGAppConnection.is_active  == True,
        ))
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="App already connected to this channel")

    conn = GGAppConnection(
        id=uuid4(),
        app_id=data.app_id,
        channel_id=ch_uuid,
        level="channel",
        connected_by=user.id,
        connection_name=data.connection_name,
        connection_status=data.connection_status,
        connection_settings=data.connection_settings,
        webhook_url=data.webhook_url,
        callback_url=data.callback_url,
        is_active=data.is_active,
        auto_sync=data.auto_sync,
        sync_interval=data.sync_interval,
        provider=data.provider,
        auth_type=data.auth_type,
    )
    db.add(conn)
    try:
        await db.commit()
        await db.refresh(conn)
    except Exception as exc:
        await db.rollback()
        if "unique" in str(exc).lower():
            raise HTTPException(status_code=409, detail="App already connected at channel scope.")
        raise

    return _conn_resp(conn, user)
