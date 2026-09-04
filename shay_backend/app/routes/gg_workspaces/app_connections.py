"""
Workspace-level GGAppConnection endpoints: list, connect, update, and
disconnect apps at workspace scope. Gmail is treated as personal OAuth and
gets a per-user visibility/uniqueness carve-out throughout.

Split from app/routes/gg_workspaces.py (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2).
"""

from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.app import App
from app.models.gg_app_connections import GGAppConnection
from app.models.user import User
from app.schemas.gg_workspace import (
    GGWorkspaceAppConnectionCreate,
    GGWorkspaceAppConnectionList,
    GGWorkspaceAppConnectionResponse,
    GGWorkspaceAppConnectionUpdate,
)
from app.utils.permissions import require_active_workspace_role

from .helpers import _conn_resp, _get_workspace_or_404, _to_uuid

router = APIRouter()


@router.get("/{workspace_id}/app-connections", response_model=GGWorkspaceAppConnectionList)
async def list_workspace_app_connections(
    workspace_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    app_id:    Optional[str]  = None,
    is_active: Optional[bool] = None,
) -> GGWorkspaceAppConnectionList:
    current_user = await get_current_user_required(request, db)
    user_id = current_user.id

    ws_uuid = _to_uuid(workspace_id, "workspace_id")
    await _get_workspace_or_404(db, ws_uuid)
    await require_active_workspace_role(
        db,
        current_user.id,
        ws_uuid,
        access_detail="Access denied to this workspace",
    )

    # Resolve Gmail app once — used in both branches below
    gmail_app = (await db.execute(
        select(App).where(func.lower(App.app_key) == "gmail")
    )).scalar_one_or_none()

    filters = [
        GGAppConnection.workspace_id == ws_uuid,
        GGAppConnection.level        == "workspace",
    ]

    if app_id:
        app_uuid = _to_uuid(app_id, "app_id")
        filters.append(GGAppConnection.app_id == app_uuid)
        # Gmail is personal OAuth — only return current user's connection
        if gmail_app and app_uuid == gmail_app.id:
            filters.append(GGAppConnection.connected_by == user_id)
    else:
        # Listing all apps — exclude other users' Gmail connections
        if gmail_app:
            filters.append(
                or_(
                    GGAppConnection.app_id != gmail_app.id,
                    and_(
                        GGAppConnection.app_id == gmail_app.id,
                        GGAppConnection.connected_by == user_id
                    )
                )
            )

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

    return GGWorkspaceAppConnectionList(
        connections=[_conn_resp(r, users_by_id.get(r.connected_by)) for r in rows],
        total=total,
        page=page,
        size=size,
        pages=(total + size - 1) // size,
    )


@router.post("/{workspace_id}/app-connections", response_model=GGWorkspaceAppConnectionResponse, status_code=201)
async def connect_workspace_app(
    workspace_id: str,
    data: GGWorkspaceAppConnectionCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> GGWorkspaceAppConnectionResponse:
    user = await get_current_user_required(request, db)

    ws_uuid = _to_uuid(workspace_id, "workspace_id")
    await _get_workspace_or_404(db, ws_uuid)

    await require_active_workspace_role(
        db,
        user.id,
        ws_uuid,
        access_detail="Access denied to this workspace",
    )

    app = (await db.execute(
        select(App).where(and_(App.id == data.app_id, App.is_active == True))
    )).scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="App not found or not active")

    # ── Gmail: per-user check | Others: per-workspace check ──────────────
    is_gmail = app.app_key.lower() == "gmail"

    duplicate_filters = [
        GGAppConnection.app_id       == data.app_id,
        GGAppConnection.workspace_id == ws_uuid,
        GGAppConnection.level        == "workspace",
        GGAppConnection.is_active    == True,
    ]
    if is_gmail:
        duplicate_filters.append(GGAppConnection.connected_by == user.id)

    existing = (await db.execute(
        select(GGAppConnection).where(and_(*duplicate_filters))
    )).scalar_one_or_none()

    if existing:
        raise HTTPException(
            status_code=409,
            detail="Your Gmail account is already connected to this workspace." if is_gmail
                   else "App already connected to this workspace"
        )
    # ─────────────────────────────────────────────────────────────────────

    conn = GGAppConnection(
        id=uuid4(),
        app_id=data.app_id,
        workspace_id=ws_uuid,
        level="workspace",
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
            raise HTTPException(status_code=409, detail="App already connected at workspace scope.")
        raise

    return _conn_resp(conn, user)


@router.put("/{workspace_id}/app-connections/{connection_id}", response_model=GGWorkspaceAppConnectionResponse)
async def update_workspace_app_connection(
    workspace_id:  str,
    connection_id: str,
    data: GGWorkspaceAppConnectionUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> GGWorkspaceAppConnectionResponse:
    """Update a workspace-level GGAppConnection."""
    user = await get_current_user_required(request, db)

    ws_uuid   = _to_uuid(workspace_id,  "workspace_id")
    conn_uuid = _to_uuid(connection_id, "connection_id")

    await _get_workspace_or_404(db, ws_uuid)
    await require_active_workspace_role(
        db,
        user.id,
        ws_uuid,
        access_detail="Access denied to this workspace",
    )

    conn = (await db.execute(
        select(GGAppConnection).where(and_(
            GGAppConnection.id           == conn_uuid,
            GGAppConnection.workspace_id == ws_uuid,
            GGAppConnection.level        == "workspace",
        ))
    )).scalar_one_or_none()

    if not conn:
        raise HTTPException(status_code=404, detail="App connection not found for this workspace")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(conn, field, value)

    await db.commit()
    await db.refresh(conn)

    connector = (await db.execute(select(User).where(User.id == conn.connected_by))).scalar_one_or_none()
    return _conn_resp(conn, connector)


@router.delete("/{workspace_id}/app-connections/{connection_id}", status_code=200)
async def disconnect_workspace_app(
    workspace_id:  str,
    connection_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Remove a GGAppConnection from a workspace."""
    user = await get_current_user_required(request, db)

    ws_uuid   = _to_uuid(workspace_id,  "workspace_id")
    conn_uuid = _to_uuid(connection_id, "connection_id")

    await _get_workspace_or_404(db, ws_uuid)
    await require_active_workspace_role(
        db,
        user.id,
        ws_uuid,
        access_detail="Access denied to this workspace",
    )

    conn = (await db.execute(
        select(GGAppConnection).where(and_(
            GGAppConnection.id           == conn_uuid,
            GGAppConnection.workspace_id == ws_uuid,
            GGAppConnection.level        == "workspace",
        ))
    )).scalar_one_or_none()

    if not conn:
        raise HTTPException(status_code=404, detail="App connection not found for this workspace")

    await db.delete(conn)
    await db.commit()
    return {"message": "App connection removed from workspace successfully"}
