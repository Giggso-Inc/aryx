"""GET /{connection_id}  get_connection

Dynamic path — must be registered after resolved.py's static /resolved so
the literal path isn't swallowed by this module's dynamic one.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.gg_app_connections import GGAppConnection
from app.models.user import User
from app.schemas.gg_app_connections import GGAppConnectionResponse

from ._shared import assert_member_access, assert_scope_exists, build_response

router = APIRouter()


@router.get("/{connection_id}", response_model=GGAppConnectionResponse)
async def get_connection(
    connection_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> GGAppConnectionResponse:
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

    connector = (await db.execute(
        select(User).where(User.id == conn.connected_by)
    )).scalar_one_or_none()

    return build_response(conn, connector)
