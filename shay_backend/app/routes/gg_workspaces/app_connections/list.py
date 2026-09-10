"""
GET /{workspace_id}/app-connections (list_workspace_app_connections) —
mounted at /api/v1/gg-workspaces.

Gmail is treated as personal OAuth and gets a per-user visibility carve-out.

Split from app/routes/gg_workspaces/app_connections.py (Raven
style-compliance pass, see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.app import App
from app.models.gg_app_connections import GGAppConnection
from app.models.user import User
from app.schemas.gg_workspace import GGWorkspaceAppConnectionList
from app.utils.permissions import require_active_workspace_role

from ..helpers import _conn_resp, _get_workspace_or_404, _to_uuid

router = APIRouter()


@router.get("/{workspace_id}/app-connections", response_model=GGWorkspaceAppConnectionList)
async def list_workspace_app_connections(
    workspace_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    app_id:    Optional[str]  = None,
    is_active: Optional[bool] = None,
) -> GGWorkspaceAppConnectionList:
    current_user = await get_current_user_required(request, db)
    user_id = current_user.id

    ws_uuid = _to_uuid(workspace_id, "workspace_id")
    await _get_workspace_or_404(db, ws_uuid)
    await require_active_workspace_role(
        db,
        current_user.id,
        ws_uuid,
        access_detail="Access denied to this workspace",
    )

    # Resolve Gmail app once — used in both branches below
    gmail_app = (await db.execute(
        select(App).where(func.lower(App.app_key) == "gmail")
    )).scalar_one_or_none()

    filters = [
        GGAppConnection.workspace_id == ws_uuid,
        GGAppConnection.level        == "workspace",
    ]

    if app_id:
        app_uuid = _to_uuid(app_id, "app_id")
        filters.append(GGAppConnection.app_id == app_uuid)
        # Gmail is personal OAuth — only return current user's connection
        if gmail_app and app_uuid == gmail_app.id:
            filters.append(GGAppConnection.connected_by == user_id)
    else:
        # Listing all apps — exclude other users' Gmail connections
        if gmail_app:
            filters.append(
                or_(
                    GGAppConnection.app_id != gmail_app.id,
                    and_(
                        GGAppConnection.app_id == gmail_app.id,
                        GGAppConnection.connected_by == user_id
                    )
                )
            )

    if is_active is not None:
        filters.append(GGAppConnection.is_active == is_active)

    base_q = select(GGAppConnection).where(and_(*filters))
    total = (await db.execute(select(func.count()).select_from(base_q.subquery()))).scalar()
    rows = (await db.execute(
        base_q.order_by(GGAppConnection.created_at.desc()).offset((page - 1) * size).limit(size)
    )).scalars().all()

    connector_ids = [r.connected_by for r in rows]
    users_by_id = {
        u.id: u for u in (
            await db.execute(select(User).where(User.id.in_(connector_ids)))
        ).scalars().all()
    } if connector_ids else {}

    return GGWorkspaceAppConnectionList(
        connections=[_conn_resp(r, users_by_id.get(r.connected_by)) for r in rows],
        total=total,
        page=page,
        size=size,
        pages=(total + size - 1) // size,
    )
