"""
GET /company — list_company_channels: all channels in the user's company
(admin view, regardless of membership).

Split out of the original app/routes/channels.py (2,630 lines) — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5.

Re-verified during wave B3 of the compliance pass: this endpoint's
per-channel metrics block was previously a ~110-line inline duplicate of the
same computation now shared via channel_metrics.compute_channel_metrics
(collect_all=False, include_provider=True matches this endpoint's prior
behavior exactly: first-match app/datasource info, plus channel_type and
provider). The earlier "too tightly coupled to extract" exception no longer
holds now that the shared helper exists — this endpoint now calls it
instead of duplicating the logic.
"""

from typing import Optional

from fastapi import APIRouter, Request, Depends, Query
from sqlalchemy import select, func, String
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.channel import Channel
from app.models.workspace import Workspace
from app.schemas.channel import ChannelResponse, ChannelList
from .channel_metrics import compute_channel_metrics

router = APIRouter()


def _apply_common_filters(query, user, search, workspace_tag, is_archived, channel_type):
    query = query.where(Channel.company_id == user.company_id)
    if search:
        query = query.where(Channel.name.ilike(f"%{search}%"))
    if workspace_tag:
        query = query.where(Workspace.name == workspace_tag)
    query = query.where(Channel.is_archived == is_archived)
    if channel_type:
        # Cast channel_type to string for comparison (handles both integer and string storage)
        query = query.where(func.lower(func.cast(Channel.channel_type, String)) == channel_type.lower())
    return query


def _apply_sort(query, sort_by, sort_order):
    # NOTE: the "last_message_at" branch and the default (else) branch use
    # different fallback columns (updated_at vs created_at) in the original
    # code — preserved exactly here rather than merged, even though
    # sort_by defaults to "last_message_at" so the else branch is rarely hit.
    asc = (sort_order or "").lower() == "asc"
    if sort_by == "name":
        return query.order_by(Channel.name.asc() if asc else Channel.name.desc())
    if sort_by == "last_message_at":
        col = func.coalesce(Channel.last_message_at, Channel.updated_at)
        return query.order_by(col.asc() if asc else col.desc())
    if sort_by == "message_count":
        return query.order_by(Channel.message_count.asc() if asc else Channel.message_count.desc())
    col = func.coalesce(Channel.last_message_at, Channel.created_at)
    return query.order_by(col.asc() if asc else col.desc())


@router.get("/company", response_model=ChannelList, tags=["Channels"])
async def list_company_channels(
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    search: Optional[str] = None,
    workspace_tag: Optional[str] = None,
    is_archived: Optional[bool] = Query(False, description="Filter by archived status. True for archived channels, False for active channels"),
    channel_type: Optional[str] = Query(None, description="Filter by channel type: email, message, regular, accsell, etc."),
    sort_by: Optional[str] = Query("last_message_at", description="Sort by: created_at, name, last_message_at, message_count"),
    sort_order: Optional[str] = Query("desc", description="Sort order: asc (ascending) or desc (descending)")
) -> ChannelList:
    """List all channels in the user's company (admin view)

    This endpoint shows all channels in the user's company, regardless of membership.
    Available sorting options:
    - sort_by: last_message_at (default), created_at, name, message_count
    - sort_order: asc (ascending) or desc (descending)
    - is_archived: Filter by archived status (default: false for active channels)
    - channel_type: Filter by channel type (e.g., email, message, regular, accsell)
    """
    user = await get_current_user_required(request)

    # Build query with workspace join
    query = select(Channel, Workspace.name.label('workspace_name')).join(
        Workspace, Channel.workspace_id == Workspace.id
    )
    query = _apply_common_filters(query, user, search, workspace_tag, is_archived, channel_type)
    query = _apply_sort(query, sort_by, sort_order)
    query = query.offset((page - 1) * size).limit(size)
    channels_with_workspaces = (await db.execute(query)).all()

    # Get total count (no sorting needed for count)
    count_query = select(func.count(Channel.id)).join(
        Workspace, Channel.workspace_id == Workspace.id
    )
    count_query = _apply_common_filters(count_query, user, search, workspace_tag, is_archived, channel_type)
    total = (await db.execute(count_query)).scalar()

    # Build response with metrics (shared with list_my / list_memberships)
    channels = []
    for channel, workspace_name in channels_with_workspaces:
        metrics = await compute_channel_metrics(db, channel, collect_all=False, include_provider=True)

        channel_response = ChannelResponse(
            id=str(channel.id),
            name=channel.name,
            description=channel.description,
            channel_tags=channel.channel_tags,
            channel_sub_tags=channel.channel_sub_tags,
            workspace_id=str(channel.workspace_id),
            workspace_name=workspace_name,
            company_id=str(channel.company_id),
            is_active=channel.is_active,
            is_public=channel.is_public,
            is_archived=channel.is_archived,
            ai_enabled=channel.ai_enabled,
            channel_settings=channel.channel_settings,
            message_count=channel.message_count,
            last_message_at=channel.last_message_at,
            total_apps_connected=metrics.total_apps_connected,
            total_users=metrics.total_users,
            total_datasources=metrics.total_datasources,
            app=metrics.app,
            datasource=metrics.datasource,
            agent_count=0,
            agent_names={},
            workflow_count=0,
            task_count=metrics.task_count,
            approval_count=metrics.approval_count,
            channel_type=metrics.channel_type,
            provider=metrics.provider,
            created_at=channel.created_at,
            updated_at=channel.updated_at
        )
        channels.append(channel_response)

    return ChannelList(
        channels=channels,
        total=total,
        page=page,
        size=size
    )
