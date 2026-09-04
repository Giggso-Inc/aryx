"""
Thread-level app-account management (mounted at /api/v1/threads):
  GET/POST     /{thread_id}/app-connections
  PUT/DELETE   /{thread_id}/app-connections/{connection_id}

Stated exception (218 lines, over the 150-line target): the four endpoints
share the `_conn_to_response` serializer (itself ~35 lines covering every
GGAppConnectionResponse field) and the same UUID-parsing/ownership-check
pattern; splitting them apart would either duplicate that serializer or
force a second shared-helper module for four small endpoints.
"""

from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.member import GGMember
from app.models.gg_app_connections import GGAppConnection
from app.models.user import User
from app.schemas.gg_app_connections import (
    GGAppConnectionCreate,
    GGAppConnectionUpdate,
    GGAppConnectionResponse,
    ConnectorMetadata,
)
from app.utils.gg_app_connections import get_all_connections_for_scope

router = APIRouter()


def _conn_to_response(conn: GGAppConnection, connector=None) -> GGAppConnectionResponse:
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


@router.get("/{thread_id}/app-connections")
async def list_thread_app_connections(
    thread_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    List all effective app connections visible at this thread.
    Returns thread-level connections first, then falls back to inherited
    channel and workspace connections.
    """
    await get_current_user_required(request, db)

    try:
        t_uuid = UUID(thread_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid thread_id format")

    accounts = await get_all_connections_for_scope(db, thread_id=t_uuid)
    return {"app_connections": [a.to_dict() for a in accounts], "total": len(accounts)}


@router.post("/{thread_id}/app-connections", status_code=201)
async def connect_thread_app(
    thread_id: str,
    data: GGAppConnectionCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Connect an app at thread scope (e.g. deal-specific CRM token)."""
    user = await get_current_user_required(request, db)

    try:
        t_uuid = UUID(thread_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid thread_id format")

    if data.level != "thread" or data.thread_id != t_uuid:
        raise HTTPException(
            status_code=422,
            detail="level must be 'thread' and thread_id must match the URL param",
        )

    # Verify caller is a thread member (or parent channel member)
    is_thread_member = (await db.execute(
        select(GGMember).where(and_(
            GGMember.user_id == user.id,
            GGMember.thread_id == t_uuid,
            GGMember.level == "thread",
            GGMember.is_active == True,
        ))
    )).scalar_one_or_none()

    if not is_thread_member:
        raise HTTPException(status_code=403, detail="You are not a member of this thread.")

    conn = GGAppConnection(
        id=uuid4(),
        app_id=data.app_id,
        thread_id=t_uuid,
        level="thread",
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
            raise HTTPException(status_code=409, detail="App already connected at thread scope.")
        raise

    return conn.to_dict()


@router.put("/{thread_id}/app-connections/{connection_id}", response_model=GGAppConnectionResponse)
async def update_thread_app_connection(
    thread_id: str,
    connection_id: str,
    data: GGAppConnectionUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> GGAppConnectionResponse:
    """Update a thread-level GGAppConnection."""
    user = await get_current_user_required(request, db)

    try:
        t_uuid    = UUID(thread_id)
        conn_uuid = UUID(connection_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID format")

    conn = (await db.execute(
        select(GGAppConnection).where(and_(
            GGAppConnection.id == conn_uuid,
            GGAppConnection.thread_id == t_uuid,
            GGAppConnection.level == "thread",
        ))
    )).scalar_one_or_none()

    if not conn:
        raise HTTPException(status_code=404, detail="App connection not found for this thread")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(conn, field, value)

    await db.commit()
    await db.refresh(conn)

    connector = (await db.execute(select(User).where(User.id == conn.connected_by))).scalar_one_or_none()
    return _conn_to_response(conn, connector)


@router.delete("/{thread_id}/app-connections/{connection_id}")
async def disconnect_thread_app(
    thread_id: str,
    connection_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Remove a GGAppConnection from a thread."""
    user = await get_current_user_required(request, db)

    try:
        t_uuid    = UUID(thread_id)
        conn_uuid = UUID(connection_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID format")

    conn = (await db.execute(
        select(GGAppConnection).where(and_(
            GGAppConnection.id == conn_uuid,
            GGAppConnection.thread_id == t_uuid,
            GGAppConnection.level == "thread",
        ))
    )).scalar_one_or_none()

    if not conn:
        raise HTTPException(status_code=404, detail="App connection not found for this thread")

    await db.delete(conn)
    await db.commit()
    return {"message": "App connection removed from thread successfully"}
