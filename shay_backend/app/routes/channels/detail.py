"""
GET /{channel_id} and GET /{channel_id}/access — single-channel read
endpoints.

Split out of the original app/routes/channels.py (2,630 lines) — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5.
"""

from fastapi import APIRouter, HTTPException, status, Request, Depends
from sqlalchemy import select, func, and_, or_, text, String
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
from app.schemas.channel_member import ChannelAccessCheckResponse
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
    # Total apps connected to this channel
    apps_count_query = select(func.count(AppAccount.id)).where(
        and_(
            AppAccount.channel_id == channel.id,
            AppAccount.is_active == True,
            AppAccount.api_key != 'email'
        )
    )
    apps_count_result = await db.execute(apps_count_query)
    total_apps_connected = apps_count_result.scalar() or 0

    # Total users in this channel
    users_count_query = select(func.count(ChannelMember.id)).where(
        and_(
            ChannelMember.channel_id == channel.id,
            ChannelMember.is_active == True
        )
    )
    users_count_result = await db.execute(users_count_query)
    total_users = users_count_result.scalar() or 0

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
    datasources_count_result = await db.execute(datasources_count_query)
    total_datasources = datasources_count_result.scalar() or 0

    # Total tasks in this channel
    tasks_count_query = select(func.count(Task.id)).where(
        Task.channel_id == channel.id
    )
    tasks_count_result = await db.execute(tasks_count_query)
    task_count = tasks_count_result.scalar() or 0

    # Total approvals in this channel
    approvals_count_query = select(func.count(Approval.id)).where(
        and_(
            Approval.channel_id == channel.id,
            Approval.is_active == "Y"
        )
    )
    approvals_count_result = await db.execute(approvals_count_query)
    approval_count = approvals_count_result.scalar() or 0

    # Get channel_type from database and provider information
    channel_type = None
    provider = None

    # Use channel_type directly from database if it's a string
    if isinstance(channel.channel_type, str):
        channel_type = channel.channel_type
    elif channel.channel_type is not None:
        # If it's an integer or other type, convert to string
        channel_type = str(channel.channel_type)

    # For email channels, get provider from AppAccount connection_settings
    if channel_type and channel_type.lower() == "email":
        email_app_account_query = select(AppAccount).where(
            and_(
                AppAccount.channel_id == channel.id,
                AppAccount.api_key == 'email',
                AppAccount.is_active == True
            )
        ).limit(1)
        email_app_account_result = await db.execute(email_app_account_query)
        email_app_account = email_app_account_result.scalar_one_or_none()

        if email_app_account and email_app_account.connection_settings:
            provider = email_app_account.connection_settings.get('provider') if isinstance(email_app_account.connection_settings, dict) else None

    # For messaging channels, get provider from gg_message_sync table
    elif channel_type and channel_type.lower() == "message":
        message_sync_query = text("""
            SELECT provider
            FROM gg_message_sync
            WHERE workspace_id = :workspace_id
            AND channel_id = :channel_id
            LIMIT 1
        """)
        message_sync_result = await db.execute(message_sync_query, {"workspace_id": str(channel.workspace_id), "channel_id": str(channel.id)})
        message_sync_row = message_sync_result.fetchone()
        if message_sync_row:
            provider = message_sync_row[0]

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


@router.get("/{channel_id}/access", response_model=ChannelAccessCheckResponse)
async def check_user_access(
    channel_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ChannelAccessCheckResponse:
    """
    Check whether the current user has access to a channel.

    This endpoint verifies if the authenticated user (from JWT token) has access to the specified channel.
    Access is determined based on company membership, channel visibility, and explicit membership.

    Author: Pranhav Vimalbalaji
    Version: 1.0.0
    Last date modified: 13/08/2025
    """
    current_user = await get_current_user_required(request)

    # Validate channel_id as UUID
    channel_uuid = validate_uuid(channel_id, "channel ID")

    stmt = select(Channel).where(Channel.id == channel_uuid)
    result = await db.execute(stmt)
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found")

    # Use current user ID from JWT token
    target_user_id = str(current_user.id)

    # Company admin has unconditional access
    if current_user.is_admin:
        return ChannelAccessCheckResponse(has_access=True, reason="admin")

    # Non-admins must be in the same company as the channel
    if str(current_user.company_id) != str(channel.company_id):
        return ChannelAccessCheckResponse(has_access=False, reason="company_mismatch")

    # Public channel → access for company users
    if channel.is_public:
        return ChannelAccessCheckResponse(has_access=True, reason="public")

    # Membership check
    member_stmt = select(ChannelMember).where(
        ChannelMember.channel_id == channel.id,
        ChannelMember.user_id == target_user_id,
        ChannelMember.is_active == True,
    )
    member_result = await db.execute(member_stmt)
    membership = member_result.scalar_one_or_none()
    if membership:
        return ChannelAccessCheckResponse(has_access=True, reason="member")

    return ChannelAccessCheckResponse(has_access=False, reason="not_member")
