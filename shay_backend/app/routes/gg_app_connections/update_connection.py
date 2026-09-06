"""PUT /{connection_id}  update_connection"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.gg_app_connections import GGAppConnection
from app.models.user import User
from app.schemas.gg_app_connections import GGAppConnectionResponse, GGAppConnectionUpdate

from ._shared import assert_member_access, assert_scope_exists, build_response

router = APIRouter()


@router.put("/{connection_id}", response_model=GGAppConnectionResponse)
async def update_connection(
    connection_id: str,
    data: GGAppConnectionUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> GGAppConnectionResponse:
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

    return build_response(conn, connector)
