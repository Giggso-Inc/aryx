"""
Workspace read endpoints: list workspaces the current user is an active
member of, and fetch a single workspace by ID.

Split from app/routes/workspaces.py (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2).
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import and_, select, func

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.member import GGMember
from app.models.workspace import Workspace
from app.schemas.workspace import WorkspaceList, WorkspaceResponse
from app.utils.permissions import require_active_workspace_role

from .helpers import _existing_bridge_for_workspace, _get_workspace_or_404, serialize_workspace

router = APIRouter()


@router.get("/", response_model=WorkspaceList)
async def list_workspaces(
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    size: int = Query(100, ge=1, le=100),
    search: Optional[str] = None
) -> WorkspaceList:
    """List workspaces for current user"""
    user = await get_current_user_required(request)

    membership_join = and_(
        GGMember.workspace_id == Workspace.id,
        GGMember.user_id == user.id,
        GGMember.level == "workspace",
        GGMember.is_active == True,  # noqa: E712
    )
    filters = [
        Workspace.company_id == user.company_id,
        Workspace.is_active == True,  # noqa: E712
    ]

    query = select(Workspace).join(GGMember, membership_join).where(*filters)

    # Add search filter
    if search:
        query = query.where(Workspace.name.ilike(f"%{search}%"))

    # Add pagination
    offset = (page - 1) * size
    query = query.offset(offset).limit(size)

    # Execute query
    result = await db.execute(query)
    workspaces = result.scalars().all()

    # Get total count
    count_query = (
        select(func.count(Workspace.id))
        .select_from(Workspace)
        .join(GGMember, membership_join)
        .where(*filters)
    )
    if search:
        count_query = count_query.where(Workspace.name.ilike(f"%{search}%"))

    count_result = await db.execute(count_query)
    total = count_result.scalar()

    bridged_workspaces = []
    for workspace in workspaces:
        # Read-only lookup, not create-or-reuse -- listing workspaces must
        # never have the side effect of creating Aryx bridge data (see
        # _existing_bridge_for_workspace's docstring).
        bridge = await _existing_bridge_for_workspace(workspace.id)
        payload = serialize_workspace(workspace).model_dump()
        payload["bridge"] = bridge
        bridged_workspaces.append(payload)

    return {
        "workspaces": bridged_workspaces,
        "total": total,
        "page": page,
        "size": size,
    }


@router.get("/{workspace_id}", response_model=WorkspaceResponse)
async def get_workspace(
    workspace_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> WorkspaceResponse:
    """Get workspace by ID"""
    user = await get_current_user_required(request)
    workspace = await _get_workspace_or_404(db, workspace_id)
    await require_active_workspace_role(db, user.id, UUID(str(workspace.id)))

    # Read-only lookup, not create-or-reuse -- see list_workspaces() above.
    bridge = await _existing_bridge_for_workspace(workspace.id)
    payload = serialize_workspace(workspace).model_dump()
    payload["bridge"] = bridge
    return payload
