"""
PUT /{workspace_id}/app-connections/{connection_id}
(update_workspace_app_connection) — mounted at /api/v1/gg-workspaces.

Split from app/routes/gg_workspaces/app_connections.py (Raven
style-compliance pass, see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.gg_app_connections import GGAppConnection
from app.models.user import User
from app.schemas.gg_workspace import GGWorkspaceAppConnectionResponse, GGWorkspaceAppConnectionUpdate
from app.utils.permissions import require_active_workspace_role

from ..helpers import _conn_resp, _get_workspace_or_404, _to_uuid

router = APIRouter()


@router.put("/{workspace_id}/app-connections/{connection_id}", response_model=GGWorkspaceAppConnectionResponse)
async def update_workspace_app_connection(
    workspace_id:  str,
    connection_id: str,
    data: GGWorkspaceAppConnectionUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> GGWorkspaceAppConnectionResponse:
    """Update a workspace-level GGAppConnection."""
    user = await get_current_user_required(request, db)

    ws_uuid   = _to_uuid(workspace_id,  "workspace_id")
    conn_uuid = _to_uuid(connection_id, "connection_id")

    await _get_workspace_or_404(db, ws_uuid)
    await require_active_workspace_role(
        db,
        user.id,
        ws_uuid,
        access_detail="Access denied to this workspace",
    )

    conn = (await db.execute(
        select(GGAppConnection).where(and_(
            GGAppConnection.id           == conn_uuid,
            GGAppConnection.workspace_id == ws_uuid,
            GGAppConnection.level        == "workspace",
        ))
    )).scalar_one_or_none()

    if not conn:
        raise HTTPException(status_code=404, detail="App connection not found for this workspace")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(conn, field, value)

    await db.commit()
    await db.refresh(conn)

    connector = (await db.execute(select(User).where(User.id == conn.connected_by))).scalar_one_or_none()
    return _conn_resp(conn, connector)
