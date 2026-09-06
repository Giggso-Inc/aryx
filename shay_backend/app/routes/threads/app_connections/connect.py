"""
POST /{thread_id}/app-connections (connect_thread_app) — mounted at
/api/v1/threads.

Split from app/routes/threads/app_connections.py (Raven style-compliance
pass, see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).
"""

from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.member import GGMember
from app.models.gg_app_connections import GGAppConnection
from app.schemas.gg_app_connections import GGAppConnectionCreate

router = APIRouter()


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
