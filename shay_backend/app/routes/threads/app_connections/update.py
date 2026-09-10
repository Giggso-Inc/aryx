"""
PUT /{thread_id}/app-connections/{connection_id} (update_thread_app_connection)
— mounted at /api/v1/threads.

Split from app/routes/threads/app_connections.py (Raven style-compliance
pass, see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.gg_app_connections import GGAppConnection
from app.models.user import User
from app.schemas.gg_app_connections import GGAppConnectionUpdate, GGAppConnectionResponse

from .serializers import conn_to_response

router = APIRouter()


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
    return conn_to_response(conn, connector)
