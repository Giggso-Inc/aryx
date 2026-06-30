"""
GG Workspace routes — workspace-level GGMember and GGAppConnection management.

Separate from the main workspaces.py router (which handles workspace CRUD).
Mounted at: /api/v1/gg-workspaces

Endpoints
─────────
  Members (gg_members, level='workspace')
    GET    /{workspace_id}/members
    POST   /{workspace_id}/members
    PUT    /{workspace_id}/members/{user_id}
    DELETE /{workspace_id}/members/{user_id}
    GET    /{workspace_id}/members/{user_id}/effective-role

  App Connections (gg_app_connections, level='workspace')
    GET    /{workspace_id}/app-connections
    POST   /{workspace_id}/app-connections
    PUT    /{workspace_id}/app-connections/{connection_id}
    DELETE /{workspace_id}/app-connections/{connection_id}
"""

from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.security import HTTPBearer
from sqlalchemy import and_, func, select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.app import App
from app.models.gg_app_connections import GGAppConnection
from app.models.member import GGMember
from app.models.user import User
from app.models.workspace import Workspace
from app.schemas.gg_workspace import (
    GGWorkspaceAppConnectionCreate,
    GGWorkspaceAppConnectionList,
    GGWorkspaceAppConnectionResponse,
    GGWorkspaceAppConnectionUpdate,
    GGWorkspaceConnectorMetadata,
    GGWorkspaceMemberCreate,
    GGWorkspaceMemberList,
    GGWorkspaceMemberResponse,
    GGWorkspaceMemberUpdate,
)
from app.utils.permissions import get_effective_role

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


def _member_resp(m: GGMember, user: Optional[User] = None) -> GGWorkspaceMemberResponse:
    return GGWorkspaceMemberResponse(
        id=str(m.id),
        user_id=str(m.user_id),
        workspace_id=str(m.workspace_id),
        level=m.level,
        role=m.role,
        is_active=m.is_active,
        permissions=m.permissions,
        invited_by=str(m.invited_by) if m.invited_by else None,
        joined_at=m.joined_at,
        created_at=m.created_at,
        updated_at=m.updated_at,
        name=user.name if user else None,
        email=user.email_id if user else None,
    )


def _conn_resp(conn: GGAppConnection, connector: Optional[User] = None) -> GGWorkspaceAppConnectionResponse:
    return GGWorkspaceAppConnectionResponse(
        id=str(conn.id),
        app_id=str(conn.app_id) if conn.app_id else None,
        workspace_id=str(conn.workspace_id),
        level=conn.level,
        connected_by=str(conn.connected_by),
        connector=GGWorkspaceConnectorMetadata(
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


async def _get_workspace_or_404(db: AsyncSession, ws_uuid: UUID) -> Workspace:
    ws = (await db.execute(select(Workspace).where(Workspace.id == ws_uuid))).scalar_one_or_none()
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return ws


# ---------------------------------------------------------------------------
# Member endpoints
# ---------------------------------------------------------------------------

@router.get("/{workspace_id}/members", response_model=GGWorkspaceMemberList)
async def list_workspace_members(
    workspace_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    role: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
):
    """List all GGMembers at workspace scope (level='workspace')."""
    user = await get_current_user_required(request, db)

    ws_uuid = _to_uuid(workspace_id, "workspace_id")
    ws = await _get_workspace_or_404(db, ws_uuid)

    if not ws.is_accessible_by_user(str(user.company_id), user.role):
        raise HTTPException(status_code=403, detail="Access denied to this workspace")

    filters = [
        GGMember.workspace_id == ws_uuid,
        GGMember.level == "workspace",
    ]
    if role:
        filters.append(GGMember.role == role)
    if is_active is not None:
        filters.append(GGMember.is_active == is_active)

    total = (await db.execute(
        select(func.count()).select_from(GGMember).where(and_(*filters))
    )).scalar()
    members = (await db.execute(
        select(GGMember).where(and_(*filters))
        .order_by(GGMember.created_at.desc())
        .offset((page - 1) * size)
        .limit(size)
    )).scalars().all()

    user_ids = [m.user_id for m in members]
    users_by_id = {
        u.id: u for u in (
            await db.execute(select(User).where(User.id.in_(user_ids)))
        ).scalars().all()
    } if user_ids else {}

    return GGWorkspaceMemberList(
        members=[_member_resp(m, users_by_id.get(m.user_id)) for m in members],
        total=total,
        page=page,
        size=size,
        pages=(total + size - 1) // size,
    )


@router.post("/{workspace_id}/members", response_model=GGWorkspaceMemberResponse, status_code=201)
async def add_workspace_member(
    workspace_id: str,
    data: GGWorkspaceMemberCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Add a user to a workspace via GGMember (level='workspace')."""
    user = await get_current_user_required(request, db)

    ws_uuid = _to_uuid(workspace_id, "workspace_id")
    ws = await _get_workspace_or_404(db, ws_uuid)

    if not ws.is_accessible_by_user(str(user.company_id), user.role):
        raise HTTPException(status_code=403, detail="Access denied to this workspace")

    member = GGMember(
        id=uuid4(),
        user_id=data.user_id,
        workspace_id=ws_uuid,
        level="workspace",
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
            raise HTTPException(status_code=409, detail="User already has a workspace membership.")
        raise

    return _member_resp(member)


@router.put("/{workspace_id}/members/{user_id}", response_model=GGWorkspaceMemberResponse)
async def update_workspace_member(
    workspace_id: str,
    user_id: str,
    data: GGWorkspaceMemberUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Update a workspace GGMember's role, permissions, or active status."""
    await get_current_user_required(request, db)

    ws_uuid   = _to_uuid(workspace_id, "workspace_id")
    user_uuid = _to_uuid(user_id,      "user_id")

    member = (await db.execute(
        select(GGMember).where(and_(
            GGMember.workspace_id == ws_uuid,
            GGMember.user_id      == user_uuid,
            GGMember.level        == "workspace",
        ))
    )).scalar_one_or_none()

    if not member:
        raise HTTPException(status_code=404, detail="Workspace membership not found")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(member, field, value)

    await db.commit()
    await db.refresh(member)
    member_user = (await db.execute(select(User).where(User.id == member.user_id))).scalar_one_or_none()
    return _member_resp(member, member_user)


@router.delete("/{workspace_id}/members/{user_id}", status_code=200)
async def remove_workspace_member(
    workspace_id: str,
    user_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Remove a GGMember from a workspace."""
    await get_current_user_required(request, db)

    ws_uuid   = _to_uuid(workspace_id, "workspace_id")
    user_uuid = _to_uuid(user_id,      "user_id")

    member = (await db.execute(
        select(GGMember).where(and_(
            GGMember.workspace_id == ws_uuid,
            GGMember.user_id      == user_uuid,
            GGMember.level        == "workspace",
        ))
    )).scalar_one_or_none()

    if not member:
        raise HTTPException(status_code=404, detail="Workspace membership not found")

    await db.delete(member)
    await db.commit()
    return {"message": "Workspace member removed successfully"}


@router.get("/{workspace_id}/members/{user_id}/effective-role")
async def get_effective_role_endpoint(
    workspace_id: str,
    user_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    channel_id: Optional[str] = Query(None),
    thread_id:  Optional[str] = Query(None),
):
    """
    Resolve the effective role for a user at the given scope.
    Resolution order: thread → channel → workspace (most specific wins).
    """
    await get_current_user_required(request, db)

    ws_uuid   = _to_uuid(workspace_id, "workspace_id")
    user_uuid = _to_uuid(user_id,      "user_id")

    ch_uuid = _to_uuid(channel_id, "channel_id") if channel_id else None
    th_uuid = _to_uuid(thread_id,  "thread_id")  if thread_id  else None

    role = await get_effective_role(
        db,
        user_id=user_uuid,
        workspace_id=ws_uuid,
        channel_id=ch_uuid,
        thread_id=th_uuid,
    )

    return {
        "user_id":        user_id,
        "effective_role": role,
        "has_access":     role is not None,
        "resolved_at":    (
            "thread"    if th_uuid and role else
            "channel"   if ch_uuid and role else
            "workspace" if role else None
        ),
    }


# ---------------------------------------------------------------------------
# App-connection endpoints
# ---------------------------------------------------------------------------

@router.get("/{workspace_id}/app-connections", response_model=GGWorkspaceAppConnectionList)
async def list_workspace_app_connections(
    workspace_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    app_id:    Optional[str]  = None,
    is_active: Optional[bool] = None,
):
    current_user = await get_current_user_required(request, db)
    user_id = current_user.id

    ws_uuid = _to_uuid(workspace_id, "workspace_id")
    await _get_workspace_or_404(db, ws_uuid)

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
):
    user = await get_current_user_required(request, db)

    ws_uuid = _to_uuid(workspace_id, "workspace_id")
    ws = await _get_workspace_or_404(db, ws_uuid)

    if not ws.is_accessible_by_user(str(user.company_id), user.role):
        raise HTTPException(status_code=403, detail="Access denied to this workspace")

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
):
    """Update a workspace-level GGAppConnection."""
    user = await get_current_user_required(request, db)

    ws_uuid   = _to_uuid(workspace_id,  "workspace_id")
    conn_uuid = _to_uuid(connection_id, "connection_id")

    ws = await _get_workspace_or_404(db, ws_uuid)
    if not ws.is_accessible_by_user(str(user.company_id), user.role):
        raise HTTPException(status_code=403, detail="Access denied to this workspace")

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
):
    """Remove a GGAppConnection from a workspace."""
    user = await get_current_user_required(request, db)

    ws_uuid   = _to_uuid(workspace_id,  "workspace_id")
    conn_uuid = _to_uuid(connection_id, "connection_id")

    ws = await _get_workspace_or_404(db, ws_uuid)
    if not ws.is_accessible_by_user(str(user.company_id), user.role):
        raise HTTPException(status_code=403, detail="Access denied to this workspace")

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
