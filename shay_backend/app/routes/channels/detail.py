"""
GET /{channel_id} — get_channel: single-channel read with metrics.

Split out of the original app/routes/channels.py (2,630 lines) — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5.

GET /{channel_id}/access (check_user_access) was further split out to
detail_access.py in wave B3 to bring this file under 150 lines; the
channel_type/provider resolution below now reuses
channel_metrics_provider.resolve_channel_type_and_provider instead of
duplicating it — this endpoint's query order/count is otherwise unchanged
(it never fetched app/datasource *info*, only the counts, so it does not
reuse channel_metrics.compute_channel_metrics, which would add two
conditional queries not present here).
"""

from fastapi import APIRouter, HTTPException, status, Request, Depends
from sqlalchemy import select, func, and_, or_, String
from sqlalchemy.sql.expression import literal
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.channel import Channel
from app.models.workspace import Workspace
from app.models.channel_member import ChannelMember
from app.models.app_account import AppAccount
from app.models.datasource import Datasource
from app.models.task import Task
from app.models.approval import Approval
from app.utils.channel_access import check_channel_access
from app.schemas.channel import ChannelResponse
from .channel_metrics_provider import resolve_channel_type_and_provider
from .helpers import validate_uuid

router = APIRouter()


@router.get("/{channel_id}", response_model=ChannelResponse)
async def get_channel(
    channel_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> ChannelResponse:
    """Get channel by ID"""
    user = await get_current_user_required(request)

    # Check channel access - user must be super admin or channel member
    await check_channel_access(db, user, channel_id)

    # Validate channel_id as UUID
    channel_uuid = validate_uuid(channel_id, "channel ID")

    # Get channel with workspace
    stmt = select(Channel, Workspace.name.label('workspace_name')).outerjoin(
        Workspace, Channel.workspace_id == Workspace.id
    ).where(Channel.id == channel_uuid)
    result = await db.execute(stmt)
    channel_data = result.first()

    if not channel_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Channel not found"
        )

    channel, workspace_name = channel_data

    # Calculate metrics for this channel
    apps_count_query = select(func.count(AppAccount.id)).where(
        and_(
            AppAccount.channel_id == channel.id,
            AppAccount.is_active == True,
            AppAccount.api_key != 'email'
        )
    )
    total_apps_connected = (await db.execute(apps_count_query)).scalar() or 0

    users_count_query = select(func.count(ChannelMember.id)).where(
        and_(
            ChannelMember.channel_id == channel.id,
            ChannelMember.is_active == True
        )
    )
    total_users = (await db.execute(users_count_query)).scalar() or 0

    # Total datasources in this channel (channel-level only; exclude thread-level)
    datasources_count_query = select(func.count(Datasource.id)).where(
        and_(
            Datasource.channel_id == channel.id,
            or_(
                Datasource.datasource_metadata.is_(None),
                ~Datasource.datasource_metadata.op("?")(literal("thread_id", type_=String()))
            )
        )
    )
    total_datasources = (await db.execute(datasources_count_query)).scalar() or 0

    task_count = (await db.execute(select(func.count(Task.id)).where(Task.channel_id == channel.id))).scalar() or 0

    approval_count = (
        await db.execute(
            select(func.count(Approval.id)).where(
                and_(Approval.channel_id == channel.id, Approval.is_active == "Y")
            )
        )
    ).scalar() or 0

    channel_type, provider = await resolve_channel_type_and_provider(db, channel)

    return ChannelResponse(
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
        total_apps_connected=total_apps_connected,
        total_users=total_users,
        total_datasources=total_datasources,
        task_count=task_count,
        approval_count=approval_count,
        channel_type=channel_type,
        provider=provider,
        created_at=channel.created_at,
        updated_at=channel.updated_at
    )
