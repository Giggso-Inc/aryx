"""
DELETE /{thread_id}/app-connections/{connection_id} (disconnect_thread_app)
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

router = APIRouter()


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
