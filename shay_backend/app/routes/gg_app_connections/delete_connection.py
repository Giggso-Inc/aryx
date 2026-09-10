"""DELETE /{connection_id}  delete_connection"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.gg_app_connections import GGAppConnection

from ._shared import assert_member_access, assert_scope_exists

router = APIRouter()


@router.delete("/{connection_id}", status_code=200)
async def delete_connection(
    connection_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
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

    company_id = await assert_scope_exists(
        db, conn.level, conn.workspace_id, conn.channel_id, conn.thread_id
    )
    await assert_member_access(
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
