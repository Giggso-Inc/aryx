"""
GET / — list_channels: channels the current user is a member of.

Split out of the original app/routes/channels.py (2,630 lines) — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5. Per-channel metrics
(apps/users/datasources/tasks/approvals/channel_type/provider) were further
extracted into channel_metrics.compute_channel_metrics in wave B2 — that
logic is shared verbatim with list_company and list_memberships rather than
duplicated here. Query-filter/sort helpers live in list_my_filters.py to
keep this file under the 150-line limit.
"""

from typing import Optional

from fastapi import APIRouter, Request, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.channel import Channel
from app.models.workspace import Workspace
from app.models.channel_member import ChannelMember
from app.schemas.channel import ChannelResponse, ChannelList
from .channel_metrics import compute_channel_metrics
from .list_my_filters import apply_common_filters, apply_sort, has_archived_channels

router = APIRouter()


@router.get("/", response_model=ChannelList)
async def list_channels(
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    search: Optional[str] = None,
    workspace_tag: Optional[str] = None,
    is_archived: Optional[bool] = Query(False, description="Filter by archived status. True for archived channels, False for active channels"),
    channel_type: Optional[str] = Query(None, description="Filter by channel type: email, message, voice etc."),
    sort_by: Optional[str] = Query("last_message_at", description="Sort by: created_at, name, last_message_at, message_count"),
    sort_order: Optional[str] = Query("desc", description="Sort order: asc (ascending) or desc (descending)")
) -> ChannelList:
    """List channels for current user with sorting and pagination

    This endpoint only shows channels where the current user is a member.
    Available sorting options:
    - sort_by: last_message_at (default), created_at, name, message_count
    - sort_order: asc (ascending) or desc (descending, default)
    - is_archived: Filter by archived status (default: false for active channels)
    - channel_type: Filter by channel type (e.g., email, message, voice )
    """
    user = await get_current_user_required(request)

    query = select(Channel, Workspace.name.label("workspace_name")).join(
        Workspace, Channel.workspace_id == Workspace.id
    ).join(ChannelMember, Channel.id == ChannelMember.channel_id)
    query = apply_common_filters(query, user, search, workspace_tag, is_archived, channel_type)
    query = apply_sort(query, sort_by, sort_order)
    query = query.offset((page - 1) * size).limit(size)
    channels_with_workspaces = (await db.execute(query)).all()

    count_query = select(func.count(Channel.id)).join(
        Workspace, Channel.workspace_id == Workspace.id
    ).join(ChannelMember, Channel.id == ChannelMember.channel_id)
    count_query = apply_common_filters(count_query, user, search, workspace_tag, is_archived, channel_type)
    total = (await db.execute(count_query)).scalar()

    has_archived = is_archived or await has_archived_channels(
        db, user, search, workspace_tag, channel_type, is_archived
    )

    channels = []
    for channel, workspace_name in channels_with_workspaces:
        metrics = await compute_channel_metrics(db, channel, collect_all=True, include_provider=True)
        channels.append(ChannelResponse(
            channel_tags=channel.channel_tags,
            channel_sub_tags=channel.channel_sub_tags,
            id=str(channel.id),
            name=channel.name,
            description=channel.description,
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
            app=metrics.app if metrics.app else None,
            datasource=metrics.datasource if metrics.datasource else None,
            task_count=metrics.task_count,
            approval_count=metrics.approval_count,
            channel_type=metrics.channel_type,
            provider=metrics.provider,
            created_at=channel.created_at,
            updated_at=channel.updated_at,
        ))

    return ChannelList(
        channels=channels,
        total=total,
        page=page,
        size=size,
        has_archived_channels=has_archived,
    )
