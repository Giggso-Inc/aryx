"""
POST /{workspace_id}/app-connections (connect_workspace_app) — mounted at
/api/v1/gg-workspaces.

Gmail is treated as personal OAuth and gets a per-user uniqueness carve-out.

Split from app/routes/gg_workspaces/app_connections.py (Raven
style-compliance pass, see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).
"""

from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.app import App
from app.models.gg_app_connections import GGAppConnection
from app.schemas.gg_workspace import GGWorkspaceAppConnectionCreate, GGWorkspaceAppConnectionResponse
from app.utils.permissions import require_active_workspace_role

from ..helpers import _conn_resp, _get_workspace_or_404, _to_uuid

router = APIRouter()


@router.post("/{workspace_id}/app-connections", response_model=GGWorkspaceAppConnectionResponse, status_code=201)
async def connect_workspace_app(
    workspace_id: str,
    data: GGWorkspaceAppConnectionCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> GGWorkspaceAppConnectionResponse:
    user = await get_current_user_required(request, db)

    ws_uuid = _to_uuid(workspace_id, "workspace_id")
    await _get_workspace_or_404(db, ws_uuid)

    await require_active_workspace_role(
        db,
        user.id,
        ws_uuid,
        access_detail="Access denied to this workspace",
    )

    app = (await db.execute(
        select(App).where(and_(App.id == data.app_id, App.is_active == True))
    )).scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="App not found or not active")

    # ── Gmail: per-user check | Others: per-workspace check ──────────────
    is_gmail = app.app_key.lower() == "gmail"

    duplicate_filters = [
        GGAppConnection.app_id       == data.app_id,
        GGAppConnection.workspace_id == ws_uuid,
        GGAppConnection.level        == "workspace",
        GGAppConnection.is_active    == True,
    ]
    if is_gmail:
        duplicate_filters.append(GGAppConnection.connected_by == user.id)

    existing = (await db.execute(
        select(GGAppConnection).where(and_(*duplicate_filters))
    )).scalar_one_or_none()

    if existing:
        raise HTTPException(
            status_code=409,
            detail="Your Gmail account is already connected to this workspace." if is_gmail
                   else "App already connected to this workspace"
        )
    # ─────────────────────────────────────────────────────────────────────

    conn = GGAppConnection(
        id=uuid4(),
        app_id=data.app_id,
        workspace_id=ws_uuid,
        level="workspace",
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
            raise HTTPException(status_code=409, detail="App already connected at workspace scope.")
        raise

    return _conn_resp(conn, user)
