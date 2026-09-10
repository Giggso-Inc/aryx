"""
Workspace update endpoint: applies field edits and keeps the bridged Aryx
workspace's name/description in sync.

Split from app/routes/workspaces.py (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2).
"""

from datetime import datetime
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.schemas.workspace import WorkspaceUpdate, WorkspaceResponse
from app.utils.permissions import require_active_workspace_role

from .helpers import _bridge_for_workspace, _get_workspace_or_404, _update_aryx_workspace_bridge, serialize_workspace

router = APIRouter()


@router.put("/{workspace_id}", response_model=WorkspaceResponse)
async def update_workspace(
    workspace_id: str,
    workspace_data: WorkspaceUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> WorkspaceResponse:
    """Update workspace"""
    user = await get_current_user_required(request)
    workspace = await _get_workspace_or_404(db, workspace_id)
    await require_active_workspace_role(db, user.id, UUID(str(workspace.id)), allowed_roles={"admin"})

    # Update workspace
    update_data = workspace_data.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(workspace, field, value)
    workspace.updated_at = datetime.utcnow()

    try:
        bridge = await _bridge_for_workspace(request, workspace)
        if bridge and bridge.get("aryx_workspace_id"):
            await _update_aryx_workspace_bridge(
                request,
                bridge["aryx_workspace_id"],
                workspace,
            )
        await db.commit()
        await db.refresh(workspace)
    except httpx.HTTPStatusError as exc:
        await db.rollback()
        detail = exc.response.text or str(exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Aryx workspace update failed: {detail}",
        ) from exc
    except httpx.RequestError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Aryx service unavailable: {exc}",
        ) from exc
    except RuntimeError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

    payload = serialize_workspace(workspace).model_dump()
    payload["bridge"] = bridge
    return payload
