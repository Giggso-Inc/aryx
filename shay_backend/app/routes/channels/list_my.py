"""
GET / — list_channels: channels the current user is a member of.

Split out of the original app/routes/channels.py (2,630 lines) — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5.
"""

from typing import Optional

from fastapi import APIRouter, Request, Depends, Query
from sqlalchemy import select, func, and_, or_, text, String
from sqlalchemy.sql.expression import literal
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.channel import Channel
from app.models.workspace import Workspace
from app.models.channel_member import ChannelMember
from app.models.app_account import AppAccount
from app.models.app import App
from app.models.datasource import Datasource
from app.models.task import Task
from app.models.approval import Approval
from app.schemas.channel import ChannelResponse, ChannelList

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

    # Build query with workspace join and channel member filter
    query = select(Channel, Workspace.name.label('workspace_name')).join(
        Workspace, Channel.workspace_id == Workspace.id
    ).join(
        ChannelMember, Channel.id == ChannelMember.channel_id
    )

    # Filter by company and user membership
    query = query.where(
        and_(
            Channel.company_id == user.company_id,
            ChannelMember.user_id == user.id,
            ChannelMember.is_active == True
        )
    )

    # Add search filter
    if search:
        query = query.where(Channel.name.ilike(f"%{search}%"))

    # Add workspace tag filter
    if workspace_tag:
        query = query.where(Workspace.name == workspace_tag)

    # Add archived status filter
    query = query.where(Channel.is_archived == is_archived)

    # Add channel_type filter
    if channel_type:
        # Cast channel_type to string for comparison (handles both integer and string storage)
        query = query.where(func.lower(func.cast(Channel.channel_type, String)) == channel_type.lower())

    # Add sorting
    if sort_by == "name":
        if sort_order.lower() == "asc":
            query = query.order_by(Channel.name.asc())
        else:
            query = query.order_by(Channel.name.desc())
    elif sort_by == "last_message_at":
        if sort_order.lower() == "asc":
            query = query.order_by(func.coalesce(Channel.last_message_at, Channel.updated_at).asc())
        else:
            query = query.order_by(func.coalesce(Channel.last_message_at, Channel.updated_at).desc())
    elif sort_by == "message_count":
        if sort_order.lower() == "asc":
            query = query.order_by(Channel.message_count.asc())
        else:
            query = query.order_by(Channel.message_count.desc())
    else:  # Default: sort by last_message_at
        if sort_order.lower() == "asc":
            query = query.order_by(func.coalesce(Channel.last_message_at, Channel.created_at).asc())
        else:
            query = query.order_by(func.coalesce(Channel.last_message_at, Channel.created_at).desc())

    # Add pagination
    offset = (page - 1) * size
    query = query.offset(offset).limit(size)

    # Execute query
    result = await db.execute(query)
    channels_with_workspaces = result.all()

    # Get total count (no sorting needed for count)
    count_query = select(func.count(Channel.id)).join(
        Workspace, Channel.workspace_id == Workspace.id
    ).join(
        ChannelMember, Channel.id == ChannelMember.channel_id
    ).where(
        and_(
            Channel.company_id == user.company_id,
            ChannelMember.user_id == user.id,
            ChannelMember.is_active == True
        )
    )

    if search:
        count_query = count_query.where(Channel.name.ilike(f"%{search}%"))
    if workspace_tag:
        count_query = count_query.where(Workspace.name == workspace_tag)

    # Add archived status filter to count query
    count_query = count_query.where(Channel.is_archived == is_archived)

    # Add channel_type filter to count query
    if channel_type:
        count_query = count_query.where(func.lower(func.cast(Channel.channel_type, String)) == channel_type.lower())

    count_result = await db.execute(count_query)
    total = count_result.scalar()

    # When listing active channels (is_archived=false), check if user has any archived channels for "Show archived" tab
    has_archived_channels = False
    if not is_archived:
        archived_count_query = select(func.count(Channel.id)).join(
            Workspace, Channel.workspace_id == Workspace.id
        ).join(
            ChannelMember, Channel.id == ChannelMember.channel_id
        ).where(
            and_(
                Channel.company_id == user.company_id,
                ChannelMember.user_id == user.id,
                ChannelMember.is_active == True,
                Channel.is_archived == True,
            )
        )
        if search:
            archived_count_query = archived_count_query.where(Channel.name.ilike(f"%{search}%"))
        if workspace_tag:
            archived_count_query = archived_count_query.where(Workspace.name == workspace_tag)
        if channel_type:
            archived_count_query = archived_count_query.where(func.lower(func.cast(Channel.channel_type, String)) == channel_type.lower())
        archived_count_result = await db.execute(archived_count_query)
        has_archived_channels = (archived_count_result.scalar() or 0) > 0
    else:
        has_archived_channels = True  # We are viewing archived list, so we have archived channels

    # Build response with metrics
    channels = []
    for channel, workspace_name in channels_with_workspaces:
        # Calculate metrics for each channel
        # Total apps connected to this channel
        apps_count_query = select(func.count(AppAccount.id)).where(
            and_(
                AppAccount.channel_id == channel.id,
                AppAccount.is_active == True,
                or_(
                    AppAccount.api_key.is_(None),
                    AppAccount.api_key != 'email'
                )
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

        # Total datasources in this channel (channel-level only; exclude thread-level e.g. email attachments)
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

        # Get app information (first connected app)
        app_info = []
        if total_apps_connected > 0:
            app_query = select(App.app_name, App.app_image).join(
                AppAccount, App.id == AppAccount.app_id
            ).where(
                and_(
                    AppAccount.channel_id == channel.id,
                    AppAccount.is_active == True
                )
            )
            app_result = await db.execute(app_query)
            app_data_list = app_result.all()
            for app_data in app_data_list:
                app_info.append({
                    "app_name": app_data.app_name,
                    "icon_url": app_data.app_image
                })

        # Get datasource information (all channel-level datasources; exclude thread-level)
        datasource_info = []
        if total_datasources > 0:
            datasource_query = select(Datasource.name, Datasource.filename, Datasource.file_type).where(
                and_(
                    Datasource.channel_id == channel.id,
                    or_(
                        Datasource.datasource_metadata.is_(None),
                        ~Datasource.datasource_metadata.op("?")(literal("thread_id", type_=String()))
                    )
                )
            )
            datasource_result = await db.execute(datasource_query)
            datasource_data_list = datasource_result.all()
            for datasource_data in datasource_data_list:
                datasource_info.append({
                    "datasource_name": datasource_data.name,
                    "file_name": datasource_data.filename,
                    "file_type": datasource_data.file_type
                })

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

        channel_response = ChannelResponse(
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
            total_apps_connected=total_apps_connected,
            total_users=total_users,
            total_datasources=total_datasources,
            app=app_info if app_info else None,
            datasource=datasource_info if datasource_info else None,
            task_count=task_count,
            approval_count=approval_count,
            channel_type=channel_type,
            provider=provider,
            created_at=channel.created_at,
            updated_at=channel.updated_at
        )
        channels.append(channel_response)

    return ChannelList(
        channels=channels,
        total=total,
        page=page,
        size=size,
        has_archived_channels=has_archived_channels,
    )
