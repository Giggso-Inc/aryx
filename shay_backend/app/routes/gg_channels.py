"""
GG Channel routes — channel-level GGMember and GGAppConnection management.

Separate from the main channels.py router (which handles channel CRUD).
Mounted at: /api/v1/gg-channels

Endpoints
─────────
  Members (gg_members, level='channel')
    GET    /{channel_id}/members
    POST   /{channel_id}/members
    PUT    /{channel_id}/members/{user_id}
    DELETE /{channel_id}/members/{user_id}

  App Connections (gg_app_connections, level='channel')
    GET    /{channel_id}/app-connections
    POST   /{channel_id}/app-connections
    PUT    /{channel_id}/app-connections/{connection_id}
    DELETE /{channel_id}/app-connections/{connection_id}
"""

from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.security import HTTPBearer
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.app import App
from app.models.channel import Channel
from app.models.gg_app_connections import GGAppConnection
from app.models.member import GGMember
from app.models.user import User
from app.schemas.gg_channels import (
    GGChannelAppConnectionCreate,
    GGChannelAppConnectionList,
    GGChannelAppConnectionResponse,
    GGChannelAppConnectionUpdate,
    GGChannelConnectorMetadata,
    GGChannelMemberCreate,
    GGChannelMemberList,
    GGChannelMemberResponse,
    GGChannelMemberUpdate,
)

router = APIRouter()
security = HTTPBearer()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_uuid(value: str, name: str) -> UUID:
    try:
        return UUID(value)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid {name} format")


def _member_resp(m: GGMember) -> GGChannelMemberResponse:
    return GGChannelMemberResponse(
        id=str(m.id),
        user_id=str(m.user_id),
        channel_id=str(m.channel_id),
        level=m.level,
        role=m.role,
        is_active=m.is_active,
        permissions=m.permissions,
        invited_by=str(m.invited_by) if m.invited_by else None,
        joined_at=m.joined_at,
        created_at=m.created_at,
        updated_at=m.updated_at,
    )


def _conn_resp(conn: GGAppConnection, connector: Optional[User] = None) -> GGChannelAppConnectionResponse:
    return GGChannelAppConnectionResponse(
        id=str(conn.id),
        app_id=str(conn.app_id) if conn.app_id else None,
        channel_id=str(conn.channel_id),
        level=conn.level,
        connected_by=str(conn.connected_by),
        connector=GGChannelConnectorMetadata(
            user_id=str(connector.id),
            name=connector.name,
            email_id=connector.email_id,
            avatar_url=connector.avatar_url,
        ) if connector else None,
        connection_name=conn.connection_name,
        connection_status=conn.connection_status,
        connection_settings=conn.connection_settings,
        webhook_url=conn.webhook_url,
        callback_url=conn.callback_url,
        is_active=conn.is_active,
        auto_sync=conn.auto_sync,
        sync_interval=conn.sync_interval,
        last_sync_at=conn.last_sync_at,
        sync_status=conn.sync_status,
        error_message=conn.error_message,
        provider=conn.provider,
        provider_account_id=conn.provider_account_id,
        auth_type=conn.auth_type,
        last_token_refresh=conn.last_token_refresh,
        token_expires_at=conn.token_expires_at,
        created_at=conn.created_at,
        updated_at=conn.updated_at,
    )


async def _get_channel_or_404(db: AsyncSession, ch_uuid: UUID) -> Channel:
    ch = (await db.execute(select(Channel).where(Channel.id == ch_uuid))).scalar_one_or_none()
    if not ch:
        raise HTTPException(status_code=404, detail="Channel not found")
    return ch


# ---------------------------------------------------------------------------
# Member endpoints
# ---------------------------------------------------------------------------

@router.get("/{channel_id}/members", response_model=GGChannelMemberList)
async def list_channel_members(
    channel_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    role:      Optional[str]  = None,
    is_active: Optional[bool] = None,
):
    """List all GGMembers at channel scope (level='channel')."""
    await get_current_user_required(request, db)

    ch_uuid = _to_uuid(channel_id, "channel_id")
    await _get_channel_or_404(db, ch_uuid)

    filters = [
        GGMember.channel_id == ch_uuid,
        GGMember.level      == "channel",
    ]
    if role:
        filters.append(GGMember.role == role)
    if is_active is not None:
        filters.append(GGMember.is_active == is_active)

    base_q = select(GGMember).where(and_(*filters))
    total = (await db.execute(select(func.count()).select_from(base_q.subquery()))).scalar()
    members = (await db.execute(
        base_q.order_by(GGMember.created_at.desc()).offset((page - 1) * size).limit(size)
    )).scalars().all()

    return GGChannelMemberList(
        members=[_member_resp(m) for m in members],
        total=total,
        page=page,
        size=size,
        pages=(total + size - 1) // size,
    )


@router.post("/{channel_id}/members", response_model=GGChannelMemberResponse, status_code=201)
async def add_channel_member(
    channel_id: str,
    data: GGChannelMemberCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Add a user to a channel via GGMember (level='channel')."""
    user = await get_current_user_required(request, db)

    ch_uuid = _to_uuid(channel_id, "channel_id")
    ch = await _get_channel_or_404(db, ch_uuid)

    if not ch.is_accessible_by_user(user.company_id, user.role):
        raise HTTPException(status_code=403, detail="Access denied to this channel")

    member = GGMember(
        id=uuid4(),
        user_id=data.user_id,
        channel_id=ch_uuid,
        level="channel",
        role=data.role,
        permissions=data.permissions or {},
        invited_by=data.invited_by or user.id,
        joined_at=datetime.utcnow(),
    )
    db.add(member)
    try:
        await db.commit()
        await db.refresh(member)
    except Exception as exc:
        await db.rollback()
        if "unique" in str(exc).lower():
            raise HTTPException(status_code=409, detail="User already has a channel membership.")
        raise

    return _member_resp(member)


@router.put("/{channel_id}/members/{user_id}", response_model=GGChannelMemberResponse)
async def update_channel_member(
    channel_id: str,
    user_id:    str,
    data: GGChannelMemberUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Update a channel GGMember's role, permissions, or active status."""
    await get_current_user_required(request, db)

    ch_uuid   = _to_uuid(channel_id, "channel_id")
    user_uuid = _to_uuid(user_id,    "user_id")

    member = (await db.execute(
        select(GGMember).where(and_(
            GGMember.channel_id == ch_uuid,
            GGMember.user_id    == user_uuid,
            GGMember.level      == "channel",
        ))
    )).scalar_one_or_none()

    if not member:
        raise HTTPException(status_code=404, detail="Channel membership not found")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(member, field, value)

    await db.commit()
    await db.refresh(member)
    return _member_resp(member)


@router.delete("/{channel_id}/members/{user_id}", status_code=200)
async def remove_channel_member(
    channel_id: str,
    user_id:    str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Remove a GGMember from a channel."""
    await get_current_user_required(request, db)

    ch_uuid   = _to_uuid(channel_id, "channel_id")
    user_uuid = _to_uuid(user_id,    "user_id")

    member = (await db.execute(
        select(GGMember).where(and_(
            GGMember.channel_id == ch_uuid,
            GGMember.user_id    == user_uuid,
            GGMember.level      == "channel",
        ))
    )).scalar_one_or_none()

    if not member:
        raise HTTPException(status_code=404, detail="Channel membership not found")

    await db.delete(member)
    await db.commit()
    return {"message": "Channel member removed successfully"}


# ---------------------------------------------------------------------------
# App-connection endpoints
# ---------------------------------------------------------------------------

@router.get("/{channel_id}/app-connections", response_model=GGChannelAppConnectionList)
async def list_channel_app_connections(
    channel_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    app_id:    Optional[str]  = None,
    is_active: Optional[bool] = None,
):
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
):
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
):
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
):
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
