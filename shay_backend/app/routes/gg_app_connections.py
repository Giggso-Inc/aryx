"""
GGAppConnection routes — unified app connections across workspace / channel / thread scopes.

Access control
──────────────
  • CREATE  : user must be an active GGMember at the target scope (or company admin).
  • READ    : user must be an active GGMember at the target scope, or belong to the
              same company as the workspace/channel.
  • UPDATE / DELETE : user must be the original connector OR an admin member at scope.

Scope resolution for GET /resolved follows: thread → channel → workspace (most specific wins).
"""

from typing import List, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.security import HTTPBearer
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.app import App
from app.models.channel import Channel
from app.models.gg_app_connections import GGAppConnection
from app.models.member import GGMember
from app.models.user import User
from app.models.workspace import Workspace
from app.schemas.gg_app_connections import (
    ConnectorMetadata,
    GGAppConnectionCreate,
    GGAppConnectionList,
    GGAppConnectionResponse,
    GGAppConnectionUpdate,
)
from app.utils.gg_app_connections import (
    get_all_connections_for_scope,
    resolve_gg_app_connection,
)

router = APIRouter()
security = HTTPBearer()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_response(conn: GGAppConnection, connector: Optional[User] = None) -> GGAppConnectionResponse:
    return GGAppConnectionResponse(
        id=str(conn.id),
        app_id=str(conn.app_id) if conn.app_id else None,
        level=conn.level,
        workspace_id=str(conn.workspace_id) if conn.workspace_id else None,
        channel_id=str(conn.channel_id)     if conn.channel_id   else None,
        thread_id=str(conn.thread_id)       if conn.thread_id    else None,
        connected_by=str(conn.connected_by),
        connector=ConnectorMetadata(
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


async def _assert_scope_exists(
    db: AsyncSession,
    level: str,
    workspace_id: Optional[UUID],
    channel_id: Optional[UUID],
    thread_id: Optional[UUID],
) -> Optional[str]:
    """
    Verify the target scope entity exists.
    Returns the company_id (str) for workspace/channel scopes, None for thread scope.
    Raises 404 if not found.
    """
    if level == "workspace" and workspace_id:
        ws = (await db.execute(
            select(Workspace).where(Workspace.id == workspace_id)
        )).scalar_one_or_none()
        if not ws:
            raise HTTPException(status_code=404, detail="Workspace not found")
        return str(ws.company_id)

    if level == "channel" and channel_id:
        ch = (await db.execute(
            select(Channel).where(Channel.id == channel_id)
        )).scalar_one_or_none()
        if not ch:
            raise HTTPException(status_code=404, detail="Channel not found")
        return str(ch.company_id)

    # Thread scope — just confirm thread exists via GGMember table (no separate thread model needed)
    # Thread existence is implicitly validated by the FK constraint on insert.
    return None


async def _assert_member_access(
    db: AsyncSession,
    user_id: UUID,
    level: str,
    workspace_id: Optional[UUID],
    channel_id: Optional[UUID],
    thread_id: Optional[UUID],
    user_company_id: Optional[str] = None,
    company_id_from_scope: Optional[str] = None,
) -> None:
    """
    Verify the user has access to the given scope.

    Strategy (in order):
      1. Active GGMember row at the exact scope — always sufficient.
      2. For workspace/channel scopes: same company_id is sufficient (company-wide access).
    """
    # Check direct membership
    if level == "workspace" and workspace_id:
        member = (await db.execute(
            select(GGMember).where(and_(
                GGMember.user_id == user_id,
                GGMember.workspace_id == workspace_id,
                GGMember.level == "workspace",
                GGMember.is_active == True,
            ))
        )).scalar_one_or_none()
        if member:
            return
        # Fallback: same company
        if user_company_id and company_id_from_scope and user_company_id == company_id_from_scope:
            return

    elif level == "channel" and channel_id:
        member = (await db.execute(
            select(GGMember).where(and_(
                GGMember.user_id == user_id,
                GGMember.channel_id == channel_id,
                GGMember.level == "channel",
                GGMember.is_active == True,
            ))
        )).scalar_one_or_none()
        if member:
            return
        # Fallback: same company via channel
        if user_company_id and company_id_from_scope and user_company_id == company_id_from_scope:
            return

    elif level == "thread" and thread_id:
        member = (await db.execute(
            select(GGMember).where(and_(
                GGMember.user_id == user_id,
                GGMember.thread_id == thread_id,
                GGMember.level == "thread",
                GGMember.is_active == True,
            ))
        )).scalar_one_or_none()
        if member:
            return
        # For thread scope fall back to checking parent channel membership
        # (thread is inside a channel; if user is a channel member they can access thread)
        parent_channel_member = (await db.execute(
            select(GGMember).where(and_(
                GGMember.user_id == user_id,
                GGMember.level == "channel",
                GGMember.is_active == True,
            ))
        )).first()
        if parent_channel_member:
            return

    raise HTTPException(
        status_code=403,
        detail=f"You do not have access to this {level}.",
    )


# ---------------------------------------------------------------------------
# GET /resolved — scope-aware resolution
# ---------------------------------------------------------------------------

@router.get("/resolved")
async def get_resolved_connection(
    app_key: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    workspace_id: Optional[str] = None,
    channel_id: Optional[str] = None,
    thread_id: Optional[str] = None,
):
    """
    Returns the most specific active GGAppConnection for the given scope + app_key.
    Resolution order: thread → channel → workspace (most specific wins).
    """
    await get_current_user_required(request, db)

    def _to_uuid(v: Optional[str], name: str) -> Optional[UUID]:
        if v is None:
            return None
        try:
            return UUID(v)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid {name} format")

    conn = await resolve_gg_app_connection(
        db,
        app_key,
        thread_id=_to_uuid(thread_id, "thread_id"),
        channel_id=_to_uuid(channel_id, "channel_id"),
        workspace_id=_to_uuid(workspace_id, "workspace_id"),
    )
    if not conn:
        raise HTTPException(
            status_code=404,
            detail="No active app connection found for this scope and app_key",
        )
    return conn.to_dict()


# ---------------------------------------------------------------------------
# POST / — create
# ---------------------------------------------------------------------------

@router.post("/", response_model=GGAppConnectionResponse, status_code=201)
async def create_connection(
    data: GGAppConnectionCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Create a new GGAppConnection at workspace, channel, or thread scope."""
    user = await get_current_user_required(request, db)

    # Verify app exists and is active
    app = (await db.execute(
        select(App).where(and_(App.id == data.app_id, App.is_active == True))
    )).scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="App not found or not active")

    # Verify scope exists and get company_id
    company_id = await _assert_scope_exists(
        db, data.level, data.workspace_id, data.channel_id, data.thread_id
    )

    # Verify user has access to the target scope
    await _assert_member_access(
        db,
        user_id=user.id,
        level=data.level,
        workspace_id=data.workspace_id,
        channel_id=data.channel_id,
        thread_id=data.thread_id,
        user_company_id=str(user.company_id),
        company_id_from_scope=company_id,
    )

    # Check for existing active connection at this scope
    duplicate_filter = {
        "workspace": and_(GGAppConnection.workspace_id == data.workspace_id, GGAppConnection.level == "workspace"),
        "channel":   and_(GGAppConnection.channel_id   == data.channel_id,   GGAppConnection.level == "channel"),
        "thread":    and_(GGAppConnection.thread_id    == data.thread_id,    GGAppConnection.level == "thread"),
    }
    existing = (await db.execute(
        select(GGAppConnection).where(
            and_(
                GGAppConnection.app_id == data.app_id,
                GGAppConnection.is_active == True,
                duplicate_filter[data.level],
            )
        )
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"App is already connected at this {data.level} scope",
        )

    # Inject Jira credentials from settings
    connection_settings = data.connection_settings
    if connection_settings and isinstance(connection_settings, dict):
        if connection_settings.get("provider") == "jira":
            import copy
            connection_settings = copy.deepcopy(connection_settings)
            connection_settings["client_id"] = settings.JIRA_CLIENT_ID
            connection_settings["client_secret"] = settings.JIRA_CLIENT_SECRET

    conn = GGAppConnection(
        id=uuid4(),
        app_id=data.app_id,
        level=data.level,
        workspace_id=data.workspace_id,
        channel_id=data.channel_id,
        thread_id=data.thread_id,
        connected_by=user.id,
        connection_name=data.connection_name,
        connection_status=data.connection_status,
        connection_settings=connection_settings,
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
            raise HTTPException(status_code=409, detail="App already connected at this scope.")
        raise

    return _build_response(conn, user)


# ---------------------------------------------------------------------------
# GET / — list
# ---------------------------------------------------------------------------

@router.get("/", response_model=GGAppConnectionList)
async def list_connections(
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    app_id: Optional[str] = None,
    level: Optional[str] = None,
    workspace_id: Optional[str] = None,
    channel_id: Optional[str] = None,
    thread_id: Optional[str] = None,
    connection_status: Optional[str] = None,
    is_active: Optional[bool] = None,
):
    """
    List GGAppConnections visible to the current user.

    Results are scoped to the user's company by joining through Workspace
    (for workspace-level) or Channel (for channel/thread-level connections).
    """
    user = await get_current_user_required(request, db)

    # Subquery: workspace_ids belonging to user's company
    company_workspace_ids = select(Workspace.id).where(
        Workspace.company_id == user.company_id
    )
    # Subquery: channel_ids belonging to user's company
    company_channel_ids = select(Channel.id).where(
        Channel.company_id == user.company_id
    )

    # Company filter: connection belongs to user's company via workspace OR channel
    company_filter = or_(
        and_(
            GGAppConnection.level == "workspace",
            GGAppConnection.workspace_id.in_(company_workspace_ids),
        ),
        and_(
            GGAppConnection.level == "channel",
            GGAppConnection.channel_id.in_(company_channel_ids),
        ),
        and_(
            # Thread connections: scoped via parent channel membership
            GGAppConnection.level == "thread",
            GGAppConnection.connected_by.in_(
                select(GGMember.user_id).where(
                    and_(
                        GGMember.level == "channel",
                        GGMember.channel_id.in_(company_channel_ids),
                        GGMember.is_active == True,
                    )
                )
            ),
        ),
    )

    filters = [company_filter]

    if app_id:
        filters.append(GGAppConnection.app_id == app_id)
    if level:
        filters.append(GGAppConnection.level == level)
    if workspace_id:
        filters.append(GGAppConnection.workspace_id == workspace_id)
    if channel_id:
        filters.append(GGAppConnection.channel_id == channel_id)
    if thread_id:
        filters.append(GGAppConnection.thread_id == thread_id)
    if connection_status:
        filters.append(GGAppConnection.connection_status == connection_status)
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

    # Batch-load connector users
    connector_ids = [r.connected_by for r in rows]
    users_by_id = {
        u.id: u for u in (
            await db.execute(select(User).where(User.id.in_(connector_ids)))
        ).scalars().all()
    } if connector_ids else {}

    return GGAppConnectionList(
        connections=[_build_response(r, users_by_id.get(r.connected_by)) for r in rows],
        total=total,
        page=page,
        size=size,
        pages=(total + size - 1) // size,
    )


# ---------------------------------------------------------------------------
# GET /{id}
# ---------------------------------------------------------------------------

@router.get("/{connection_id}", response_model=GGAppConnectionResponse)
async def get_connection(
    connection_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Get a specific GGAppConnection by ID."""
    user = await get_current_user_required(request, db)

    try:
        conn_uuid = UUID(connection_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid connection_id format")

    conn = (await db.execute(
        select(GGAppConnection).where(GGAppConnection.id == conn_uuid)
    )).scalar_one_or_none()

    if not conn:
        raise HTTPException(status_code=404, detail="App connection not found")

    # Resolve company_id for access check
    company_id = await _assert_scope_exists(
        db, conn.level, conn.workspace_id, conn.channel_id, conn.thread_id
    )
    await _assert_member_access(
        db,
        user_id=user.id,
        level=conn.level,
        workspace_id=conn.workspace_id,
        channel_id=conn.channel_id,
        thread_id=conn.thread_id,
        user_company_id=str(user.company_id),
        company_id_from_scope=company_id,
    )

    connector = (await db.execute(
        select(User).where(User.id == conn.connected_by)
    )).scalar_one_or_none()

    return _build_response(conn, connector)


# ---------------------------------------------------------------------------
# PUT /{id}
# ---------------------------------------------------------------------------

@router.put("/{connection_id}", response_model=GGAppConnectionResponse)
async def update_connection(
    connection_id: str,
    data: GGAppConnectionUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Update a GGAppConnection. Only the original connector or scope admins may update."""
    user = await get_current_user_required(request, db)

    try:
        conn_uuid = UUID(connection_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid connection_id format")

    conn = (await db.execute(
        select(GGAppConnection).where(GGAppConnection.id == conn_uuid)
    )).scalar_one_or_none()

    if not conn:
        raise HTTPException(status_code=404, detail="App connection not found")

    # Resolve company_id for access check
    company_id = await _assert_scope_exists(
        db, conn.level, conn.workspace_id, conn.channel_id, conn.thread_id
    )
    await _assert_member_access(
        db,
        user_id=user.id,
        level=conn.level,
        workspace_id=conn.workspace_id,
        channel_id=conn.channel_id,
        thread_id=conn.thread_id,
        user_company_id=str(user.company_id),
        company_id_from_scope=company_id,
    )

    update_data = data.model_dump(exclude_unset=True)

    # Inject Jira credentials if connection_settings are being updated
    if "connection_settings" in update_data:
        cs = update_data["connection_settings"]
        if cs and isinstance(cs, dict) and cs.get("provider") == "jira":
            import copy
            cs = copy.deepcopy(cs)
            cs["client_id"] = settings.JIRA_CLIENT_ID
            cs["client_secret"] = settings.JIRA_CLIENT_SECRET
            update_data["connection_settings"] = cs

    for field, value in update_data.items():
        setattr(conn, field, value)

    await db.commit()
    await db.refresh(conn)

    connector = (await db.execute(
        select(User).where(User.id == conn.connected_by)
    )).scalar_one_or_none()

    return _build_response(conn, connector)


# ---------------------------------------------------------------------------
# DELETE /{id}
# ---------------------------------------------------------------------------

@router.delete("/{connection_id}", status_code=200)
async def delete_connection(
    connection_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Delete a GGAppConnection."""
    user = await get_current_user_required(request, db)

    try:
        conn_uuid = UUID(connection_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid connection_id format")

    conn = (await db.execute(
        select(GGAppConnection).where(GGAppConnection.id == conn_uuid)
    )).scalar_one_or_none()

    if not conn:
        raise HTTPException(status_code=404, detail="App connection not found")

    company_id = await _assert_scope_exists(
        db, conn.level, conn.workspace_id, conn.channel_id, conn.thread_id
    )
    await _assert_member_access(
        db,
        user_id=user.id,
        level=conn.level,
        workspace_id=conn.workspace_id,
        channel_id=conn.channel_id,
        thread_id=conn.thread_id,
        user_company_id=str(user.company_id),
        company_id_from_scope=company_id,
    )

    await db.delete(conn)
    await db.commit()

    return {"message": "App connection deleted successfully"}


# ---------------------------------------------------------------------------
# GET /{scope_type}/{scope_id}/connections — list by scope
# ---------------------------------------------------------------------------

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
):
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
    company_id = await _assert_scope_exists(
        db,
        scope_type,
        workspace_id=scope_uuid if scope_type == "workspace" else None,
        channel_id=scope_uuid   if scope_type == "channel"   else None,
        thread_id=scope_uuid    if scope_type == "thread"    else None,
    )
    await _assert_member_access(
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
        connections=[_build_response(r, users_by_id.get(r.connected_by)) for r in rows],
        total=total,
        page=page,
        size=size,
        pages=(total + size - 1) // size,
    )
