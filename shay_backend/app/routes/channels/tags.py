"""
GET /tags — list_workspace_tags: workspace-tag listing endpoint used to
populate the "workspace tag" picker in channel creation UIs.

Split out of the original app/routes/channels.py (2,630 lines) — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5.

GET /workspaces (list_workspaces) was further split out to
tags_workspaces.py in wave B3 to bring this file under 150 lines.
"""

from typing import Optional

from fastapi import APIRouter, Request, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.channel import Channel
from app.models.workspace import Workspace
from app.schemas.channel import WorkspaceTagResponse, WorkspaceTagList

router = APIRouter()


@router.get("/tags", response_model=WorkspaceTagList)
async def list_workspace_tags(
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    search: Optional[str] = None,
    sort_by: Optional[str] = Query("name", description="Sort by: name, channel_count, created_at"),
    sort_order: Optional[str] = Query("asc", description="Sort order: asc (ascending) or desc (descending)")
) -> WorkspaceTagList:
    """List available workspace tags (workspaces) for the user's company with sorting and pagination

    Available sorting options:
    - sort_by: name (default), channel_count, created_at
    - sort_order: asc (ascending, default) or desc (descending)
    """
    user = await get_current_user_required(request)

    # Build query with channel count
    query = select(
        Workspace,
        func.count(Channel.id).label('channel_count')
    ).outerjoin(
        Channel, Workspace.id == Channel.workspace_id
    ).where(
        Workspace.company_id == user.company_id
    ).group_by(Workspace.id)

    # Add search filter
    if search:
        query = query.where(Workspace.name.ilike(f"%{search}%"))

    # Add sorting
    if sort_by == "channel_count":
        if sort_order.lower() == "asc":
            query = query.order_by(func.count(Channel.id).asc())
        else:
            query = query.order_by(func.count(Channel.id).desc())
    elif sort_by == "created_at":
        if sort_order.lower() == "asc":
            query = query.order_by(Workspace.created_at.asc())
        else:
            query = query.order_by(Workspace.created_at.desc())
    else:  # Default: sort by name
        if sort_order.lower() == "asc":
            query = query.order_by(Workspace.name.asc())
        else:
            query = query.order_by(Workspace.name.desc())

    # Add pagination
    offset = (page - 1) * size
    query = query.offset(offset).limit(size)

    # Execute query
    result = await db.execute(query)
    workspaces_with_counts = result.all()

    # Get total count
    count_query = select(func.count(Workspace.id)).where(
        Workspace.company_id == user.company_id
    )
    if search:
        count_query = count_query.where(Workspace.name.ilike(f"%{search}%"))

    count_result = await db.execute(count_query)
    total = count_result.scalar()

    # Build response
    tags = []
    for workspace, channel_count in workspaces_with_counts:
        tag_response = WorkspaceTagResponse(
            id=str(workspace.id),
            name=workspace.name,
            description=workspace.description,
            channel_count=channel_count,
            created_at=workspace.created_at
        )
        tags.append(tag_response)

    return WorkspaceTagList(
        tags=tags,
        total=total,
        page=page,
        size=size
    )
