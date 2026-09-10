"""
GET /message-channels — list_message_channels.

Split out of the original app/routes/channels.py (2,630 lines) — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5.
"""

import uuid
from typing import List, Optional

from fastapi import APIRouter, Request, Depends, Query
from sqlalchemy import select, func, and_, or_, String
from sqlalchemy.sql.expression import literal
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.channel import Channel
from app.models.workspace import Workspace
from app.models.channel_member import ChannelMember
from app.models.task import Task
from app.models.approval import Approval
from app.schemas.channel import ChannelResponse

router = APIRouter()


@router.get("/message-channels", response_model=List[ChannelResponse], tags=["Channels"])
async def list_message_channels(
    request: Request,
    db: AsyncSession = Depends(get_db),
    workspace_id: uuid.UUID = Query(..., description="Workspace ID; returns message channels for this workspace and user's company"),
    search: Optional[str] = None,
    is_archived: Optional[bool] = Query(False, description="Filter by archived status. False = active channels only"),
    sort_by: Optional[str] = Query("last_message_at", description="Sort by: created_at, name, last_message_at, message_count"),
    sort_order: Optional[str] = Query("desc", description="Sort order: asc or desc"),
) -> List[ChannelResponse]:
    """
    List regular (message/chat) channels for the current user's company and the given workspace.
    Returns only channels the current user is a member of. Excludes WhatsApp; only regular channels.
    Response is a list of channels (no pagination).
    """
    user = await get_current_user_required(request)
    # Message type: DB may store as VARCHAR ('1', 'message') or INTEGER; cast to string for comparison
    channel_type_str = func.coalesce(func.cast(Channel.channel_type, String), "")
    message_type_filter = or_(
        func.lower(channel_type_str) == "1",
        func.lower(channel_type_str) == "message",
    )
    # Exclude WhatsApp: only regular channels (channel_settings->>'provider' != 'whatsapp' or provider null)
    provider_key = literal("provider", type_=String())
    whatsapp_val = literal("whatsapp", type_=String())
    regular_only_filter = or_(
        Channel.channel_settings.is_(None),
        Channel.channel_settings.op("->>")(provider_key).is_(None),
        Channel.channel_settings.op("->>")(provider_key) != whatsapp_val,
    )
    query = (
        select(Channel, Workspace.name.label("workspace_name"))
        .join(Workspace, Channel.workspace_id == Workspace.id)
        .join(ChannelMember, and_(Channel.id == ChannelMember.channel_id, ChannelMember.user_id == user.id, ChannelMember.is_active == True))
        .where(
            and_(
                Channel.company_id == user.company_id,
                Channel.workspace_id == workspace_id,
                Channel.is_active == True,
                Channel.is_archived == is_archived,
                message_type_filter,
                regular_only_filter,
            )
        )
    )
    if search:
        query = query.where(Channel.name.ilike(f"%{search}%"))
    if sort_by == "name":
        query = query.order_by(Channel.name.asc() if sort_order and sort_order.lower() == "asc" else Channel.name.desc())
    elif sort_by == "message_count":
        query = query.order_by(Channel.message_count.asc() if sort_order and sort_order.lower() == "asc" else Channel.message_count.desc())
    elif sort_by == "created_at":
        query = query.order_by(Channel.created_at.asc() if sort_order and sort_order.lower() == "asc" else Channel.created_at.desc())
    else:
        query = query.order_by(
            func.coalesce(Channel.last_message_at, Channel.created_at).asc()
            if sort_order and sort_order.lower() == "asc"
            else func.coalesce(Channel.last_message_at, Channel.created_at).desc()
        )
    result = await db.execute(query)
    channels_with_workspaces = result.all()
    channels = []
    for channel, workspace_name in channels_with_workspaces:
        users_count_result = await db.execute(
            select(func.count(ChannelMember.id)).where(
                and_(
                    ChannelMember.channel_id == channel.id,
                    ChannelMember.is_active == True,
                )
            )
        )
        total_users = users_count_result.scalar() or 0
        tasks_count_result = await db.execute(select(func.count(Task.id)).where(Task.channel_id == channel.id))
        task_count = tasks_count_result.scalar() or 0
        approvals_count_result = await db.execute(
            select(func.count(Approval.id)).where(
                and_(Approval.channel_id == channel.id, Approval.is_active == "Y")
            )
        )
        approval_count = approvals_count_result.scalar() or 0
        channel_type_val = (
            channel.channel_type if isinstance(channel.channel_type, str) else str(channel.channel_type)
            if channel.channel_type is not None else None
        )
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
            total_apps_connected=0,
            total_users=total_users,
            total_datasources=0,
            app=None,
            datasource=None,
            agent_count=0,
            agent_names={},
            workflow_count=0,
            task_count=task_count,
            approval_count=approval_count,
            channel_type=channel_type_val,
            provider=None,
            created_at=channel.created_at,
            updated_at=channel.updated_at,
        )
        channels.append(channel_response)
    return channels
