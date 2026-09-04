"""
Workspace creation: creates the Shay workspace row, seeds the creator's
admin GGMember, and bridges it to Aryx — rolling back all three Shay-side
writes if the Aryx bridge call fails.

Split from app/routes/workspaces.py (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2).
"""

from datetime import datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete

from app.core.database import get_db
from app.core.auth import generate_workspace_id
from app.middleware.auth_middleware import get_current_user_required
from app.models.member import GGMember
from app.models.workspace import Workspace
from app.schemas.workspace import WorkspaceCreate, WorkspaceResponse
from app.services.workspace_membership import ensure_workspace_membership

from .helpers import _bridge_for_workspace, serialize_workspace

router = APIRouter()


@router.post("/", response_model=WorkspaceResponse)
async def create_workspace(
    workspace_data: WorkspaceCreate,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> WorkspaceResponse:
    """Create a new workspace"""
    user = await get_current_user_required(request)

    # Check if user can create workspaces
    if not user.can_manage_workspace(user.company_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions to create workspace"
        )

    now = datetime.utcnow()

    # Create workspace
    workspace = Workspace(
        id=generate_workspace_id(),
        name=workspace_data.name,
        description=workspace_data.description,
        company_id=user.company_id,
        is_public=workspace_data.is_public,
        ai_enabled=workspace_data.ai_enabled,
        ai_provider=workspace_data.ai_provider,
        ai_model=workspace_data.ai_model,
        settings=workspace_data.settings,
        workspace_type=workspace_data.workspace_type,
        user_id=user.id,
        created_by=user.id,
        created_at=now,
        updated_at=now,
    )

    db.add(workspace)
    await db.flush()
    await ensure_workspace_membership(
        db,
        workspace=workspace,
        user=user,
        role="admin",
    )
    try:
        await db.commit()
        await db.refresh(workspace)
        bridge = await _bridge_for_workspace(request, workspace)
    except httpx.HTTPStatusError as exc:
        # rollback is a no-op after commit; delete the orphaned rows explicitly
        await db.execute(delete(GGMember).where(GGMember.workspace_id == workspace.id))
        await db.execute(delete(Workspace).where(Workspace.id == workspace.id))
        await db.commit()
        detail = exc.response.text or str(exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Aryx workspace bridge creation failed: {detail}",
        ) from exc
    except httpx.RequestError as exc:
        await db.execute(delete(GGMember).where(GGMember.workspace_id == workspace.id))
        await db.execute(delete(Workspace).where(Workspace.id == workspace.id))
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Aryx service unavailable: {exc}",
        ) from exc
    except RuntimeError as exc:
        await db.execute(delete(GGMember).where(GGMember.workspace_id == workspace.id))
        await db.execute(delete(Workspace).where(Workspace.id == workspace.id))
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

    payload = serialize_workspace(workspace).model_dump()
    payload["bridge"] = bridge
    return payload
