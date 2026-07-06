"""
Thread CRUD and thread-level member / app-connection overrides.

Thread CRUD endpoints (mounted at /api/v1/threads):
  POST   /                   create thread
  GET    /                   list threads (channel_id required)
  GET    /{thread_id}        get thread
  PUT    /{thread_id}        update thread
  DELETE /{thread_id}        delete thread (admin only)

Thread-level member/app-connection overrides:
  GET/POST/PUT/DELETE /{thread_id}/members
  GET/POST/PUT/DELETE /{thread_id}/app-connections
"""

from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.security import HTTPBearer
from sqlalchemy import and_, select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.auth import generate_workspace_id
from app.middleware.auth_middleware import get_current_user_required
from app.models.channel import Channel
from app.models.member import GGMember
from app.models.message import Thread, Message
from app.models.gg_app_connections import GGAppConnection
from app.models.app import App
from app.schemas.message import (
    ThreadCreate,
    ThreadUpdate,
    ThreadResponse,
    ThreadList,
)
from app.schemas.member import MemberCreate, MemberUpdate, MemberResponse, MemberList
from app.schemas.gg_app_connections import (
    GGAppConnectionCreate,
    GGAppConnectionUpdate,
    GGAppConnectionResponse,
    ConnectorMetadata,
)
from app.utils.gg_app_connections import get_all_connections_for_scope
from app.models.user import User

router = APIRouter()
security = HTTPBearer()


# ---------------------------------------------------------------------------
# Thread CRUD
# ---------------------------------------------------------------------------

@router.post("/", response_model=ThreadResponse, status_code=201)
async def create_thread(
    thread_data: ThreadCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Create a new thread in a channel."""
    user = await get_current_user_required(request, db)

    try:
        channel_uuid = UUID(thread_data.channel_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid channel_id format")

    channel = (await db.execute(select(Channel).where(Channel.id == channel_uuid))).scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    if not channel.is_accessible_by_user(str(user.company_id), user.role):
        raise HTTPException(status_code=403, detail="Access denied to channel")

    thread = Thread(
        id=generate_workspace_id(),
        title=thread_data.title,
        description=thread_data.description,
        channel_id=channel_uuid,
        ai_enabled=channel.ai_enabled,
    )
    db.add(thread)
    await db.commit()
    await db.refresh(thread)

    return ThreadResponse(
        id=str(thread.id),
        title=thread.title,
        description=thread.description,
        channel_id=str(thread.channel_id),
        is_active=thread.is_active,
        is_archived=thread.is_archived,
        message_count=thread.message_count,
        last_message_at=thread.last_message_at,
        ai_enabled=thread.ai_enabled,
        ai_summary=thread.ai_summary,
        created_at=thread.created_at,
        updated_at=thread.updated_at,
    )


@router.get("/", response_model=ThreadList)
async def list_threads(
    channel_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    search: Optional[str] = Query(None, description="Search by thread title"),
    is_archived: Optional[bool] = Query(False, description="Filter by archived status"),
    sort_by: Optional[str] = Query("last_message_at", description="Sort by: created_at, updated_at, last_message_at, message_count"),
    sort_order: Optional[str] = Query("desc", description="Sort order: asc or desc"),
):
    """List threads in a channel."""
    user = await get_current_user_required(request, db)

    channel = (await db.execute(select(Channel).where(Channel.id == channel_id))).scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    if not channel.is_accessible_by_user(str(user.company_id), user.role):
        raise HTTPException(status_code=403, detail="Access denied to channel")

    query = select(Thread).where(Thread.channel_id == channel_id, Thread.is_archived == is_archived)
    if search:
        query = query.where(Thread.title.ilike(f"%{search}%"))

    sort_col = {
        "created_at": Thread.created_at,
        "updated_at": Thread.updated_at,
        "message_count": Thread.message_count,
    }.get(sort_by)
    if sort_col is not None:
        query = query.order_by(sort_col.asc() if sort_order == "asc" else sort_col.desc())
    else:
        coalesced = func.coalesce(Thread.last_message_at, Thread.created_at)
        query = query.order_by(coalesced.asc() if sort_order == "asc" else coalesced.desc())

    count_query = select(func.count(Thread.id)).where(Thread.channel_id == channel_id, Thread.is_archived == is_archived)
    if search:
        count_query = count_query.where(Thread.title.ilike(f"%{search}%"))
    total = (await db.execute(count_query)).scalar()

    threads = (await db.execute(query.offset((page - 1) * size).limit(size))).scalars().all()

    thread_responses = []
    for thread in threads:
        first_msg = (await db.execute(
            select(Message.id).where(Message.thread_id == thread.id).order_by(Message.sequence_number.asc()).limit(1)
        )).scalar_one_or_none()
        thread_responses.append(ThreadResponse(
            id=str(thread.id),
            title=thread.title,
            description=thread.description,
            channel_id=str(thread.channel_id),
            is_active=thread.is_active,
            is_archived=thread.is_archived,
            message_count=thread.message_count,
            last_message_at=thread.last_message_at,
            ai_enabled=thread.ai_enabled,
            ai_summary=thread.ai_summary,
            first_message_id=str(first_msg) if first_msg else None,
            created_at=thread.created_at,
            updated_at=thread.updated_at,
        ))

    return ThreadList(threads=thread_responses, total=total, page=page, size=size)


@router.get("/{thread_id}", response_model=ThreadResponse)
async def get_thread(
    thread_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Get thread details by ID."""
    user = await get_current_user_required(request, db)

    thread = (await db.execute(select(Thread).where(Thread.id == thread_id))).scalar_one_or_none()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    channel = (await db.execute(select(Channel).where(Channel.id == thread.channel_id))).scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    if not channel.is_accessible_by_user(str(user.company_id), user.role):
        raise HTTPException(status_code=403, detail="Access denied to channel")

    first_msg = (await db.execute(
        select(Message.id).where(Message.thread_id == thread.id).order_by(Message.sequence_number.asc()).limit(1)
    )).scalar_one_or_none()

    return ThreadResponse(
        id=str(thread.id),
        title=thread.title,
        description=thread.description,
        channel_id=str(thread.channel_id),
        is_active=thread.is_active,
        is_archived=thread.is_archived,
        message_count=thread.message_count,
        last_message_at=thread.last_message_at,
        ai_enabled=thread.ai_enabled,
        ai_summary=thread.ai_summary,
        first_message_id=str(first_msg) if first_msg else None,
        created_at=thread.created_at,
        updated_at=thread.updated_at,
    )


@router.put("/{thread_id}", response_model=ThreadResponse)
async def update_thread(
    thread_id: str,
    thread_update: ThreadUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Update a thread's title, description, status, or AI settings."""
    user = await get_current_user_required(request, db)

    thread = (await db.execute(select(Thread).where(Thread.id == thread_id))).scalar_one_or_none()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    channel = (await db.execute(select(Channel).where(Channel.id == thread.channel_id))).scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    if not channel.is_accessible_by_user(str(user.company_id), user.role):
        raise HTTPException(status_code=403, detail="Access denied to channel")

    for field, value in thread_update.model_dump(exclude_unset=True).items():
        setattr(thread, field, value)
    thread.updated_at = datetime.utcnow()

    await db.commit()
    await db.refresh(thread)

    return ThreadResponse(
        id=str(thread.id),
        title=thread.title,
        description=thread.description,
        channel_id=str(thread.channel_id),
        is_active=thread.is_active,
        is_archived=thread.is_archived,
        message_count=thread.message_count,
        last_message_at=thread.last_message_at,
        ai_enabled=thread.ai_enabled,
        ai_summary=thread.ai_summary,
        created_at=thread.created_at,
        updated_at=thread.updated_at,
    )


@router.delete("/{thread_id}")
async def delete_thread(
    thread_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Delete a thread and all its messages (admin only)."""
    user = await get_current_user_required(request, db)

    thread = (await db.execute(select(Thread).where(Thread.id == thread_id))).scalar_one_or_none()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    channel = (await db.execute(select(Channel).where(Channel.id == thread.channel_id))).scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    if not channel.is_accessible_by_user(str(user.company_id), user.role):
        raise HTTPException(status_code=403, detail="Access denied to channel")
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Only administrators can delete threads")

    message_count = (await db.execute(
        select(func.count(Message.id)).where(Message.thread_id == thread_id)
    )).scalar()

    await db.delete(thread)
    await db.commit()

    return {
        "message": "Thread deleted successfully",
        "thread_id": thread_id,
        "messages_deleted": message_count,
    }


# ---------------------------------------------------------------------------
# Thread-level member management
# ---------------------------------------------------------------------------

@router.get("/{thread_id}/members", response_model=MemberList)
async def list_thread_members(
    thread_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
):
    """List thread-level member overrides (level='thread' only)."""
    await get_current_user_required(request, db)

    try:
        t_uuid = UUID(thread_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid thread_id format")

    offset = (page - 1) * size
    stmt = (
        select(GGMember)
        .where(and_(GGMember.thread_id == t_uuid, GGMember.level == "thread"))
        .offset(offset)
        .limit(size)
    )
    result = await db.execute(stmt)
    members = result.scalars().all()

    count_stmt = select(func.count(GGMember.id)).where(
        and_(GGMember.thread_id == t_uuid, GGMember.level == "thread")
    )
    total = (await db.execute(count_stmt)).scalar()

    return MemberList(
        members=[_member_to_response(m) for m in members],
        total=total,
        page=page,
        size=size,
    )


@router.post("/{thread_id}/members", response_model=MemberResponse, status_code=201)
async def add_thread_member(
    thread_id: str,
    member_data: MemberCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Add (or override) a user's role at thread level."""
    await get_current_user_required(request, db)

    try:
        t_uuid = UUID(thread_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid thread_id format")

    if member_data.level != "thread" or str(member_data.thread_id) != thread_id:
        raise HTTPException(
            status_code=422,
            detail="level must be 'thread' and thread_id in body must match the URL param",
        )

    member = GGMember(
        id=uuid4(),
        user_id=member_data.user_id,
        thread_id=t_uuid,
        level="thread",
        role=member_data.role,
        permissions=member_data.permissions or {},
        invited_by=member_data.invited_by,
        joined_at=datetime.utcnow(),
    )
    db.add(member)
    try:
        await db.commit()
        await db.refresh(member)
    except Exception as exc:
        await db.rollback()
        if "unique" in str(exc).lower():
            raise HTTPException(status_code=409, detail="User already has a thread-level membership.")
        raise

    return _member_to_response(member)


@router.put("/{thread_id}/members/{user_id}", response_model=MemberResponse)
async def update_thread_member(
    thread_id: str,
    user_id: str,
    member_data: MemberUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Update a thread-level member override."""
    await get_current_user_required(request, db)

    try:
        t_uuid = UUID(thread_id)
        u_uuid = UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID format")

    stmt = select(GGMember).where(and_(
        GGMember.thread_id == t_uuid,
        GGMember.user_id == u_uuid,
        GGMember.level == "thread",
    ))
    result = await db.execute(stmt)
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=404, detail="Thread membership not found")

    for field, value in member_data.model_dump(exclude_unset=True).items():
        setattr(member, field, value)

    await db.commit()
    await db.refresh(member)
    return _member_to_response(member)


@router.delete("/{thread_id}/members/{user_id}")
async def remove_thread_member(
    thread_id: str,
    user_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Remove a thread-level membership override."""
    await get_current_user_required(request, db)

    try:
        t_uuid = UUID(thread_id)
        u_uuid = UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID format")

    stmt = select(GGMember).where(and_(
        GGMember.thread_id == t_uuid,
        GGMember.user_id == u_uuid,
        GGMember.level == "thread",
    ))
    result = await db.execute(stmt)
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=404, detail="Thread membership not found")

    await db.delete(member)
    await db.commit()
    return {"message": "Thread membership removed successfully"}


# ---------------------------------------------------------------------------
# Thread-level app-account management
# ---------------------------------------------------------------------------

@router.get("/{thread_id}/app-connections")
async def list_thread_app_connections(
    thread_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
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
):
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
):
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
):
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


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

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


def _member_to_response(m: GGMember) -> MemberResponse:
    return MemberResponse(
        id=str(m.id),
        user_id=str(m.user_id),
        level=m.level,
        workspace_id=str(m.workspace_id) if m.workspace_id else None,
        channel_id=str(m.channel_id)     if m.channel_id   else None,
        thread_id=str(m.thread_id)       if m.thread_id    else None,
        role=m.role,
        is_active=m.is_active,
        permissions=m.permissions,
        invited_by=str(m.invited_by) if m.invited_by else None,
        joined_at=m.joined_at,
        created_at=m.created_at,
        updated_at=m.updated_at,
    )
