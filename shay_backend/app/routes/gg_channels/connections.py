"""
Channel-level GGAppConnection endpoints: list, connect, update, disconnect.

Split from the original app/routes/gg_channels.py (Raven style-compliance
pass, see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2).
"""

from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.app import App
from app.models.gg_app_connections import GGAppConnection
from app.models.user import User
from app.schemas.gg_channels import (
    GGChannelAppConnectionCreate,
    GGChannelAppConnectionList,
    GGChannelAppConnectionResponse,
    GGChannelAppConnectionUpdate,
)

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
