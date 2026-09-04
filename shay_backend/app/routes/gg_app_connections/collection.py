"""
Collection-level gg_app_connections endpoints (mounted at the package root):
  GET  /resolved   get_resolved_connection  (must stay registered before
                    detail.py's dynamic GET /{connection_id} — a static
                    single-segment path would otherwise be swallowed by it)
  POST /           create_connection
  GET  /           list_connections
"""

from typing import Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
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
    GGAppConnectionCreate,
    GGAppConnectionList,
    GGAppConnectionResponse,
)
from app.utils.gg_app_connections import resolve_gg_app_connection

from ._shared import assert_member_access, assert_scope_exists, build_response

router = APIRouter()


@router.get("/resolved")
async def get_resolved_connection(
    app_key: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    workspace_id: Optional[str] = None,
    channel_id: Optional[str] = None,
    thread_id: Optional[str] = None,
) -> dict:
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


@router.post("/", response_model=GGAppConnectionResponse, status_code=201)
async def create_connection(
    data: GGAppConnectionCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> GGAppConnectionResponse:
    """Create a new GGAppConnection at workspace, channel, or thread scope."""
    user = await get_current_user_required(request, db)

    # Verify app exists and is active
    app = (await db.execute(
        select(App).where(and_(App.id == data.app_id, App.is_active == True))
    )).scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="App not found or not active")

    # Verify scope exists and get company_id
    company_id = await assert_scope_exists(
        db, data.level, data.workspace_id, data.channel_id, data.thread_id
    )

    # Verify user has access to the target scope
    await assert_member_access(
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

    return build_response(conn, user)


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
) -> GGAppConnectionList:
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
        connections=[build_response(r, users_by_id.get(r.connected_by)) for r in rows],
        total=total,
        page=page,
        size=size,
        pages=(total + size - 1) // size,
    )
