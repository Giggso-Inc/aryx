"""
Channel routes for CRUD operations with automatic workspace management

Author: Karthick Chandrasekar, Pranhav Vimal
Date: 2025-08-14, 2025-01-27
Version: 1.0.0, 1.1.0

Recent Changes:
Author: Pranhav Vimal
Date: 2025-01-27
Version: 1.2.0
- Added agent_count, agent_names, workflow_count, and RCA fields to channel responses
- Enhanced list_company_channels and list_my_channel_memberships endpoints with additional metadata
"""

from typing import List, Optional
from fastapi import APIRouter, HTTPException, status, Request, Depends, Query, File, UploadFile
from fastapi.security import HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_, delete, text, String
from sqlalchemy.sql.expression import literal
from datetime import datetime
import uuid

from app.core.database import get_db
from app.core.auth import generate_channel_id, generate_workspace_id
from app.core.config import settings
from app.middleware.auth_middleware import get_current_user_required
from app.models.user import User
from app.models.channel import Channel
from app.models.workspace import Workspace
from app.models.channel_member import ChannelMember
from app.models.company import Company
from app.models.app_account import AppAccount
from app.models.app import App
from app.models.datasource import Datasource
from app.models.task import Task
from app.models.approval import Approval
from app.services.audit_service import log as audit_log_write
from app.services.email_service import email_service
from app.utils.channel_access import check_channel_access
from app.schemas.channel import (
    ChannelCreate,
    ChannelUpdate,
    ChannelResponse,
    ChannelList,
    WorkspaceTagResponse,
    WorkspaceTagList,
)
from app.schemas.channel_member import (
    SingleChannelMemberCreate,
    ChannelMemberResponse,
    ChannelMemberList,
    ChannelAccessCheckResponse,
    ChannelMemberUserList,
    ChannelMemberUserResponse,
    ChannelMemberUpdate,
    ChannelMemberUpdateResponse,
)

router = APIRouter()
security = HTTPBearer()


def validate_uuid(uuid_string: str, field_name: str = "ID") -> uuid.UUID:
    """Validate and return UUID from string, or raise HTTPException if invalid"""
    try:
        return uuid.UUID(uuid_string)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid {field_name} format. Must be a valid UUID."
        )


async def get_channel_admins(channel_id: uuid.UUID, db: AsyncSession) -> List[User]:
    """
    Get all admin users for a channel
    
    Args:
        channel_id: Channel UUID
        db: Database session
        
    Returns:
        List[User]: List of admin users for the channel
    """
    # Find all channel members with admin role
    admin_members_stmt = select(ChannelMember).where(
        and_(
            ChannelMember.channel_id == channel_id,
            ChannelMember.role.ilike("admin"),  # Case-insensitive match
            ChannelMember.is_active == True
        )
    )
    admin_members_result = await db.execute(admin_members_stmt)
    admin_members = admin_members_result.scalars().all()
    
    # Get user objects for admin members
    admin_user_ids = [member.user_id for member in admin_members]
    
    if not admin_user_ids:
        return []
    
    users_stmt = select(User).where(
        and_(
            User.id.in_(admin_user_ids),
            User.is_active == True
        )
    )
    users_result = await db.execute(users_stmt)
    admin_users = users_result.scalars().all()
    
    return list(admin_users)


@router.post("/", response_model=ChannelResponse)
async def create_channel(
    channel_data: ChannelCreate,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Create a new channel with automatic workspace management"""
    user = await get_current_user_required(request)
    
    # Check if user can create channels
    if not user.can_manage_workspace(user.company_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions to create channel"
        )
    
    # Validate that either workspace_tag or workspace_id is provided
    if not channel_data.workspace_tag and not channel_data.workspace_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either workspace_tag or workspace_id must be provided"
        )
    
    if channel_data.workspace_tag and channel_data.workspace_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot provide both workspace_tag and workspace_id. Choose one."
        )
    
    workspace = None
    
    # Scenario 1: User provides workspace_id (existing workspace)
    if channel_data.workspace_id:
        try:
            from uuid import UUID
            workspace_uuid = UUID(channel_data.workspace_id)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid workspace_id format"
            )
        
        # Check if workspace exists and belongs to user's company
        workspace_stmt = select(Workspace).where(
            and_(
                Workspace.id == workspace_uuid,
                Workspace.company_id == user.company_id,
                Workspace.is_active == True
            )
        )
        workspace_result = await db.execute(workspace_stmt)
        workspace = workspace_result.scalar_one_or_none()
        
        if not workspace:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Workspace not found or you don't have access to it"
            )
    
    # Scenario 2: User provides workspace_tag (create or find existing workspace)
    else:
        # Check if workspace (tag) already exists for this company
        workspace_stmt = select(Workspace).where(
            and_(
                Workspace.name == channel_data.workspace_tag,
                Workspace.company_id == user.company_id,
                Workspace.is_active == True
            )
        )
        workspace_result = await db.execute(workspace_stmt)
        workspace = workspace_result.scalar_one_or_none()
        
        # If workspace doesn't exist, create it
        if not workspace:
            workspace = Workspace(
                id=generate_workspace_id(),
                name=channel_data.workspace_tag,
                description=f"Auto-created workspace for tag: {channel_data.workspace_tag}",
                company_id=user.company_id,
                is_public=channel_data.is_public,
                ai_enabled=channel_data.ai_enabled,
                ai_provider="openai",
                ai_model="gpt-4",
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            db.add(workspace)
            await db.flush()  # Flush to get the workspace ID
    
    # Check if channel with same name already exists in this workspace
    existing_channel_stmt = select(Channel).where(
        and_(
            Channel.name == channel_data.name,
            Channel.workspace_id == workspace.id,
            Channel.company_id == user.company_id
        )
    )
    existing_channel_result = await db.execute(existing_channel_stmt)
    existing_channel = existing_channel_result.scalar_one_or_none()
    
    if existing_channel:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Channel with name '{channel_data.name}' already exists in workspace '{workspace.name}'"
        )
    
    # Optional channel_tags / channel_sub_tags: store null in DB when not provided or empty
    channel_tags_value = channel_data.channel_tags if (channel_data.channel_tags and len(channel_data.channel_tags) > 0) else None
    channel_sub_tags_value = channel_data.channel_sub_tags if (channel_data.channel_sub_tags and len(channel_data.channel_sub_tags) > 0) else None

    # Create channel
    channel = Channel(
        id=generate_channel_id(),
        name=channel_data.name,
        description=channel_data.description,
        channel_tags=channel_tags_value,
        channel_sub_tags=channel_sub_tags_value,
        workspace_id=workspace.id,
        company_id=user.company_id,
        is_public=channel_data.is_public,
        is_archived=channel_data.is_archived,
        ai_enabled=channel_data.ai_enabled,
        channel_settings=channel_data.channel_settings,
        created_by=user.id,
        updated_by=user.id,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )
    
    db.add(channel)
    await db.flush()  # Flush to get the channel ID
    
    # Add the channel creator as a member with admin role
    channel_member = ChannelMember(
        id=generate_channel_id(),
        channel_id=channel.id,
        user_id=user.id,
        role="admin",  # Channel creator gets admin role
        permissions={"can_manage": True, "can_post": True, "can_invite": True},
        is_active=True,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )
    db.add(channel_member)
    await audit_log_write(db, user.id, "channel.created", "channel", channel.id, channel_id=channel.id)
    await db.commit()
    await db.refresh(channel)
    await db.refresh(workspace)
    
    # Create response with workspace name and metrics (new channels start with 1 user - the creator)
    # Task and approval counts for new channel (will be 0)
    task_count = 0
    approval_count = 0
    
    response_data = ChannelResponse(
        id=str(channel.id),
        name=channel.name,
        description=channel.description,
        channel_tags=channel.channel_tags,
        channel_sub_tags=channel.channel_sub_tags,
        workspace_id=str(channel.workspace_id),
        workspace_name=workspace.name,
        company_id=str(channel.company_id),
        is_active=channel.is_active,
        is_public=channel.is_public,
        is_archived=channel.is_archived,
        ai_enabled=channel.ai_enabled,
        channel_settings=channel.channel_settings,
        message_count=channel.message_count,
        last_message_at=channel.last_message_at,
        total_apps_connected=0,  # New channel has no apps connected
        total_users=1,  # New channel has 1 user (the creator)
        total_datasources=0,  # New channel has no datasources yet
        task_count=task_count,
        approval_count=approval_count,
        created_at=channel.created_at,
        updated_at=channel.updated_at
    )
    
    return response_data


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
):
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


@router.get("/message-channels", response_model=List[ChannelResponse], tags=["Channels"])
async def list_message_channels(
    request: Request,
    db: AsyncSession = Depends(get_db),
    workspace_id: uuid.UUID = Query(..., description="Workspace ID; returns message channels for this workspace and user's company"),
    search: Optional[str] = None,
    is_archived: Optional[bool] = Query(False, description="Filter by archived status. False = active channels only"),
    sort_by: Optional[str] = Query("last_message_at", description="Sort by: created_at, name, last_message_at, message_count"),
    sort_order: Optional[str] = Query("desc", description="Sort order: asc or desc"),
):
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
):
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
    
    # Filter by company only
    query = query.where(Channel.company_id == user.company_id)
    
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
            query = query.order_by(func.coalesce(Channel.last_message_at, Channel.updated_at).asc())
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
    ).where(Channel.company_id == user.company_id)
    
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
        
        # Get app information (first connected app)
        app_info = None
        if total_apps_connected > 0:
            app_query = select(App.app_name, App.app_image).join(
                AppAccount, App.id == AppAccount.app_id
            ).where(
                and_(
                    AppAccount.channel_id == channel.id,
                    AppAccount.is_active == True
                )
            ).limit(1)
            app_result = await db.execute(app_query)
            app_data = app_result.first()
            if app_data:
                app_info = {
                    "app_name": app_data.app_name,
                    "icon_url": app_data.app_image
                }
        
        # Get datasource information (first channel-level datasource)
        datasource_info = None
        if total_datasources > 0:
            datasource_query = select(Datasource.name, Datasource.filename, Datasource.file_type).where(
                and_(
                    Datasource.channel_id == channel.id,
                    or_(
                        Datasource.datasource_metadata.is_(None),
                        ~Datasource.datasource_metadata.op("?")(literal("thread_id", type_=String()))
                    )
                )
            ).limit(1)
            datasource_result = await db.execute(datasource_query)
            datasource_data = datasource_result.first()
            if datasource_data:
                datasource_info = {
                    "datasource_name": datasource_data.name,
                    "file_name": datasource_data.filename,
                    "file_type": datasource_data.file_type
                }
        
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
            app=app_info,
            datasource=datasource_info,
            agent_count=0,
            agent_names={},
            workflow_count=0,
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
        size=size
    )


@router.get("/my-memberships", response_model=ChannelList, tags=["Channels"])
async def list_my_channel_memberships(
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
):
    """List channels where the current user is a member (same as / endpoint)
    
    This endpoint shows channels where the current user is a member.
    Available sorting options:
    - sort_by: last_message_at (default), created_at, name, message_count
    - sort_order: asc (ascending) or desc (descending, default)
    - is_archived: Filter by archived status (default: false for active channels)
    - channel_type: Filter by channel type (e.g., email, message, regular, accsell)
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
            query = query.order_by(func.coalesce(Channel.last_message_at, Channel.created_at).asc())
        else:
            query = query.order_by(func.coalesce(Channel.last_message_at, Channel.created_at).desc())
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
        apps_count_query_result = await db.execute(apps_count_query)
        total_apps_connected = apps_count_query_result.scalar() or 0
        
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
        
        # Get app information (first connected app)
        app_info = None
        if total_apps_connected > 0:
            app_query = select(App.app_name, App.app_image).join(
                AppAccount, App.id == AppAccount.app_id
            ).where(
                and_(
                    AppAccount.channel_id == channel.id,
                    AppAccount.is_active == True
                )
            ).limit(1)
            app_result = await db.execute(app_query)
            app_data = app_result.first()
            if app_data:
                app_info = {
                    "app_name": app_data.app_name,
                    "icon_url": app_data.app_image
                }
        
        # Get datasource information (first channel-level datasource)
        datasource_info = None
        if total_datasources > 0:
            datasource_query = select(Datasource.name, Datasource.filename, Datasource.file_type).where(
                and_(
                    Datasource.channel_id == channel.id,
                    or_(
                        Datasource.datasource_metadata.is_(None),
                        ~Datasource.datasource_metadata.op("?")(literal("thread_id", type_=String()))
                    )
                )
            ).limit(1)
            datasource_result = await db.execute(datasource_query)
            datasource_data = datasource_result.first()
            if datasource_data:
                datasource_info = {
                    "datasource_name": datasource_data.name,
                    "file_name": datasource_data.filename,
                    "file_type": datasource_data.file_type
                }
        
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
            total_apps_connected=total_apps_connected,
            total_users=total_users,
            total_datasources=total_datasources,
            app=app_info,
            datasource=datasource_info,
            agent_count=0,
            agent_names={},
            workflow_count=0,
            task_count=task_count,
            approval_count=approval_count,
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


@router.get("/tags", response_model=WorkspaceTagList)
async def list_workspace_tags(
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    search: Optional[str] = None,
    sort_by: Optional[str] = Query("name", description="Sort by: name, channel_count, created_at"),
    sort_order: Optional[str] = Query("asc", description="Sort order: asc (ascending) or desc (descending)")
):
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


@router.get("/workspaces", response_model=WorkspaceTagList)
async def list_workspaces(
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    search: Optional[str] = None,
    sort_by: Optional[str] = Query("name", description="Sort by: name, channel_count, created_at"),
    sort_order: Optional[str] = Query("asc", description="Sort order: asc (ascending) or desc (descending)")
):
    """List available workspaces for channel creation with sorting and pagination
    
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
        and_(
            Workspace.company_id == user.company_id,
            Workspace.is_active == True
        )
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
        and_(
            Workspace.company_id == user.company_id,
            Workspace.is_active == True
        )
    )
    if search:
        count_query = count_query.where(Workspace.name.ilike(f"%{search}%"))
    
    count_result = await db.execute(count_query)
    total = count_result.scalar()
    
    # Build response
    workspaces = []
    for workspace, channel_count in workspaces_with_counts:
        workspace_response = WorkspaceTagResponse(
            id=str(workspace.id),
            name=workspace.name,
            description=workspace.description,
            channel_count=channel_count,
            created_at=workspace.created_at
        )
        workspaces.append(workspace_response)
    
    return WorkspaceTagList(
        tags=workspaces,
        total=total,
        page=page,
        size=size
    )


@router.get("/{channel_id}", response_model=ChannelResponse)
async def get_channel(
    channel_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
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
):
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


# ============================================================================
# Channel Member Management Endpoints
# ============================================================================
# Two ways to add users to channels:
# 1. Single user by email: POST /{channel_id}/members
# 2. Multiple users by CSV: POST /{channel_id}/members/bulk-csv
# ============================================================================


# Primary endpoint: Single user addition by email (mail_id)
@router.post("/{channel_id}/members", response_model=ChannelMemberResponse)
async def add_channel_member(
    channel_id: str,
    body: SingleChannelMemberCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Grant access to a single user for the given channel id by email.
    
    This endpoint allows company admins or users with workspace management permissions to add a single
    member to a channel. It supports both creating new memberships and updating existing ones (upsert behavior).
    
    Input format:
    {
        "mail_id": "user@example.com",
        "role": "Admin",
        "permissions": {"can_manage": true}
    }
    
    Allowed roles: User, Admin (case-insensitive)
    
    Author: Pranhav Vimalbalaji
    Version: 1.0.0
    Last date modified: 13/08/2025
    """
    current_user = await get_current_user_required(request)

    # Validate channel_id as UUID
    channel_uuid = validate_uuid(channel_id, "channel ID")

    # Fetch channel
    stmt = select(Channel).where(Channel.id == channel_uuid)
    result = await db.execute(stmt)
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found")

    # Authorization: user must be company admin or able to manage within same company
    if not current_user.is_admin and str(current_user.company_id) != str(channel.company_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cross-company access denied")
    if not current_user.is_admin and not current_user.can_manage_workspace(str(channel.company_id)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    # KEY DIFFERENCE: This endpoint finds users by email (mail_id) instead of requiring user_id
    # This makes it easier to add users without needing to know their internal user ID
    # Find user by email_id (mail_id) - this allows adding users by email instead of requiring user_id
    user_stmt = select(User).where(
        and_(
            User.email_id == body.mail_id,
            User.company_id == channel.company_id,
            User.is_active == True
        )
    )
    user_result = await db.execute(user_stmt)
    user = user_result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with email {body.mail_id} not found or does not belong to this company"
        )

    # Check if user is already a member of this channel - implement upsert behavior
    # If user exists, update their role and permissions; if not, create new membership
    existing_stmt = select(ChannelMember).where(
        ChannelMember.channel_id == channel.id,
        ChannelMember.user_id == user.id,
    )
    existing_result = await db.execute(existing_stmt)
    existing = existing_result.scalar_one_or_none()
    
    if existing:
        # Update existing membership (upsert behavior)
        existing.role = body.role
        if body.permissions is not None:
            existing.permissions = body.permissions
        existing.is_active = True
        await audit_log_write(db, current_user.id, "channel.member_updated", "channel", channel_uuid, channel_id=channel_uuid, details={"member_id": str(user.id)})
        await db.commit()
        await db.refresh(existing)
        
        return ChannelMemberResponse(
            id=str(existing.id),
            channel_id=str(existing.channel_id),
            user_id=str(existing.user_id),
            role=existing.role,
            is_active=existing.is_active,
        )
    else:
        # Create new membership (user wasn't previously in this channel)
        member = ChannelMember(
            id=generate_channel_id(),  # Generate unique ID for new channel member
            channel_id=channel.id,
            user_id=user.id,
            role=body.role,
            permissions=body.permissions,
            is_active=True,
        )
        db.add(member)
        await audit_log_write(db, current_user.id, "channel.member_added", "channel", channel.id, channel_id=channel.id, details={"member_id": str(user.id)})
        await db.commit()
        await db.refresh(member)

        # Email: Accsell/Zaptag → requirement flow only (added user, View Channel); others → previous flow (notify channel admins)
        try:
            # [DEBUG] Log raw body value so we can verify platform_name/platformName from request
            platform_name = body.platform_name or settings.PLATFORM_NAME
            platform_lower = str(platform_name or '').strip().lower()
            print(f"📧 [channel add-member] body.platform_name={body.platform_name!r}, resolved platform_name={platform_name!r}, platform_lower={platform_lower!r}, branch={'accsell/zaptag (to added user)' if platform_lower in ('accsell', 'zaptag') else 'admin (to admins)'}")
            if platform_lower in ('accsell', 'zaptag'):
                # Accsell/Zaptag: send only to the added user with "You have been added" + View Channel button (requirement flow)
                notification_data_user = {
                    'channel_id': str(channel.id),
                    'channel_name': channel.name,
                    'user_name': user.name or user.email_id.split('@')[0],
                    'user_email': user.email_id,
                    'user_role': body.role,
                    'added_by': current_user.name or current_user.email_id.split('@')[0],
                    'platform_name': platform_name,
                    'send_to_added_user': True
                }
                # View Channel URL: use SHAY_PLATFORM_URL when platform is Accsell and set, else PLATFORM_URL
                base_url = (settings.SHAY_PLATFORM_URL or settings.PLATFORM_URL) if platform_lower == 'accsell' else settings.PLATFORM_URL
                # [DEBUG] Confirm payload before calling email service
                print(f"📧 [channel add-member] Sending to added user: to_emails=[{user.email_id}], notification_data keys={list(notification_data_user.keys())}, send_to_added_user={notification_data_user.get('send_to_added_user')!r}, platform_url={base_url!r}")
                email_sent_user = email_service.send_channel_member_notification(
                    to_emails=[user.email_id],
                    notification_data=notification_data_user,
                    platform_url=base_url
                )
                if email_sent_user:
                    print(f"✅ Channel member notification (added user) sent to {user.email_id}")
                else:
                    print(f"⚠️ Channel member notification (added user) failed to send")
            else:
                # Previous flow: send email notification to channel admins (unchanged for non-Accsell/Zaptag; no send_to_added_user)
                print(f"📧 Preparing to notify channel admins about new member {user.email_id}...")
                channel_admins = await get_channel_admins(channel.id, db)
                if channel_admins:
                    admin_emails = [admin.email_id for admin in channel_admins if admin.email_id]
                    if admin_emails:
                        # Do not add send_to_added_user here; email_service uses its absence for admin subject/body
                        notification_data = {
                            'channel_name': channel.name,
                            'user_name': user.name or user.email_id.split('@')[0],
                            'user_email': user.email_id,
                            'user_role': body.role,
                            'added_by': current_user.name or current_user.email_id.split('@')[0],
                            'platform_name': platform_name
                        }
                        email_sent = email_service.send_channel_member_notification(
                            to_emails=admin_emails,
                            notification_data=notification_data,
                            platform_url=settings.PLATFORM_URL
                        )
                        if email_sent:
                            print(f"✅ Channel member notification emails sent successfully to {len(admin_emails)} admins")
                        else:
                            print(f"⚠️ Some channel member notification emails failed to send")
                else:
                    print(f"ℹ️ No channel admins found to notify")
        except Exception as email_error:
            # Log email error but don't fail the member addition
            print(f"⚠️ Error sending channel member notification (non-critical): {email_error}")
            import traceback
            print(f"📋 Email error traceback: {traceback.format_exc()}")

        return ChannelMemberResponse(
            id=str(member.id),
            channel_id=str(member.channel_id),
            user_id=str(member.user_id),
            role=member.role,
            is_active=member.is_active,
        )


@router.get("/{channel_id}/members", response_model=ChannelMemberUserList)
async def list_channel_members(
    channel_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    include_inactive: bool = Query(False, description="Include inactive memberships"),
    search: Optional[str] = Query(None, description="Filter by user name or email contains"),
):
    """
    List users who have access to a channel (members), with pagination and optional search.
    
    This endpoint provides a paginated list of channel members with user details. Admins can view
    regardless of company; non-admins must belong to the same company.
    
    Author: Pranhav Vimalbalaji
    Version: 1.0.0
    Last date modified: 13/08/2025
    """
    current_user = await get_current_user_required(request)

    # Check channel access - user must be super admin or channel member
    await check_channel_access(db, current_user, channel_id)

    # Validate channel_id as UUID
    channel_uuid = validate_uuid(channel_id, "channel ID")

    # Ensure channel exists
    stmt = select(Channel).where(Channel.id == channel_uuid)
    result = await db.execute(stmt)
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found")

    # Build base query joining users and company for richer info
    from app.models.user import User

    filters = [ChannelMember.channel_id == channel.id]
    if not include_inactive:
        filters.append(ChannelMember.is_active == True)

    # Join to users and company (left join since company_id might be null)
    base_query = (
        select(ChannelMember, User, Company)
        .join(User, User.id == ChannelMember.user_id)
        .outerjoin(Company, Company.id == User.company_id)
        .where(*filters)
        .order_by(User.name.nullslast(), User.email_id.nullslast())
    )

    if search:
        like = f"%{search}%"
        base_query = base_query.where(
            (User.name.ilike(like)) | (User.email_id.ilike(like))
        )

    # Pagination
    offset = (page - 1) * size
    items_query = base_query.offset(offset).limit(size)
    items_res = await db.execute(items_query)
    rows = items_res.all()

    # Count
    count_query = (
        select(func.count(ChannelMember.id))
        .join(User, User.id == ChannelMember.user_id)
        .where(*filters)
    )
    if search:
        like = f"%{search}%"
        count_query = count_query.where((User.name.ilike(like)) | (User.email_id.ilike(like)))
    total = (await db.execute(count_query)).scalar()

    items = [
        ChannelMemberUserResponse(
            user_id=str(user.id),
            email_id=user.email_id,
            name=user.name,
            avatar_url=user.avatar_url,
            user_role=user.role,
            membership_role=member.role,
            company_id=str(company.id) if company else None,
            company_name=company.name if company else None,
        )
        for member, user, company in rows
    ]

    return ChannelMemberUserList(items=items, total=total)


@router.put("/{channel_id}/members/{update_user_id}", response_model=ChannelMemberUpdateResponse)
async def update_channel_member(
    channel_id: str,
    update_user_id: str,
    update_data: ChannelMemberUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Update a channel member's role and permissions.
    
    This endpoint allows admins to modify the role and permissions of existing channel members.
    Only company administrators have permission to update member roles.
    
    Author: Pranhav Vimalbalaji
    Version: 1.0.0
    Last date modified: 13/08/2025
    """
    current_user = await get_current_user_required(request)

    # Only admins can update member roles
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can update member roles"
        )

    # Validate channel_id as UUID
    channel_uuid = validate_uuid(channel_id, "channel ID")

    # Check if channel exists
    stmt = select(Channel).where(Channel.id == channel_uuid)
    result = await db.execute(stmt)
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found")

    # Validate update_user_id as UUID
    update_user_uuid = validate_uuid(update_user_id, "user ID")

    # Check if membership exists
    member_stmt = select(ChannelMember).where(
        ChannelMember.channel_id == channel.id,
        ChannelMember.user_id == update_user_uuid,
    )
    member_result = await db.execute(member_stmt)
    member = member_result.scalar_one_or_none()
    if not member:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User is not a member of this channel"
        )

    # Update member role and permissions
    member.role = update_data.role
    if update_data.permissions is not None:
        member.permissions = update_data.permissions
    member.updated_at = datetime.utcnow()
    await audit_log_write(db, current_user.id, "channel.member_updated", "channel", channel_uuid, channel_id=channel_uuid, details={"member_id": str(update_user_uuid)})
    await db.commit()
    await db.refresh(member)

    updated_member = ChannelMemberResponse(
        id=str(member.id),
        channel_id=str(member.channel_id),
        user_id=str(member.user_id),
        role=member.role,
        is_active=member.is_active,
    )

    return ChannelMemberUpdateResponse(
        message="Member role updated successfully",
        updated_member=updated_member
    )


@router.delete("/{channel_id}/members/{delete_user_id}")
async def remove_channel_member(
    channel_id: str,
    delete_user_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Remove a user's access to a channel.
    
    This endpoint allows admins to remove a user's membership from a channel. Only company
    administrators have permission to remove channel members.
    
    Author: Pranhav Vimalbalaji
    Version: 1.0.0
    Last date modified: 13/08/2025
    """
    current_user = await get_current_user_required(request)

    # Only admins can remove members
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can remove channel members"
        )

    # Validate channel_id as UUID
    channel_uuid = validate_uuid(channel_id, "channel ID")

    # Check if channel exists
    stmt = select(Channel).where(Channel.id == channel_uuid)
    result = await db.execute(stmt)
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found")

    # Validate delete_user_id as UUID
    delete_user_uuid = validate_uuid(delete_user_id, "user ID")

    # Check if membership exists
    member_stmt = select(ChannelMember).where(
        ChannelMember.channel_id == channel.id,
        ChannelMember.user_id == delete_user_uuid,
    )
    member_result = await db.execute(member_stmt)
    member = member_result.scalar_one_or_none()
    if not member:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User is not a member of this channel"
        )

    await audit_log_write(db, current_user.id, "channel.member_removed", "channel", channel_uuid, channel_id=channel_uuid, details={"member_id": str(delete_user_uuid)})
    await db.delete(member)
    await db.commit()

    return {"message": "Member removed from channel successfully"}


@router.put("/{channel_id}", response_model=ChannelResponse)
async def update_channel(
    channel_id: str,
    channel_data: ChannelUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Update channel. All body fields optional. Example: {"channel_tags": ["support"], "channel_sub_tags": ["tier1"]}. Send [] or null to clear."""
    user = await get_current_user_required(request)
    
    # Validate channel_id as UUID
    channel_uuid = validate_uuid(channel_id, "channel ID")
    
    # Get channel
    stmt = select(Channel).where(Channel.id == channel_uuid)
    result = await db.execute(stmt)
    channel = result.scalar_one_or_none()
    
    if not channel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Channel not found"
        )
    
    # Check permissions
    if not channel.is_accessible_by_user(user.company_id, user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to channel"
        )
    
    # If name is being updated, check for conflicts
    if channel_data.name and channel_data.name != channel.name:
        existing_channel_stmt = select(Channel).where(
            and_(
                Channel.name == channel_data.name,
                Channel.workspace_id == channel.workspace_id,
                Channel.company_id == user.company_id,
                Channel.id != channel.id  # Exclude current channel from check
            )
        )
        existing_channel_result = await db.execute(existing_channel_stmt)
        existing_channel = existing_channel_result.scalars().first()
        
        if existing_channel:
            # Get workspace name for error message
            workspace_stmt = select(Workspace.name).where(Workspace.id == channel.workspace_id)
            workspace_result = await db.execute(workspace_stmt)
            workspace_name = workspace_result.scalar()
            
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Channel with name '{channel_data.name}' already exists in workspace '{workspace_name}'"
            )
    
    # Update channel (channel_tags / channel_sub_tags optional; store null when not provided or empty)
    update_data = channel_data.dict(exclude_unset=True)
    if 'channel_tags' in update_data and (update_data['channel_tags'] is None or len(update_data['channel_tags']) == 0):
        update_data['channel_tags'] = None
    if 'channel_sub_tags' in update_data and (update_data['channel_sub_tags'] is None or len(update_data['channel_sub_tags']) == 0):
        update_data['channel_sub_tags'] = None
    for field, value in update_data.items():
        setattr(channel, field, value)
    await audit_log_write(db, user.id, "channel.updated", "channel", channel_uuid, channel_id=channel_uuid)
    await db.commit()
    await db.refresh(channel)
    
    # Get workspace name for response
    workspace_stmt = select(Workspace.name).where(Workspace.id == channel.workspace_id)
    workspace_result = await db.execute(workspace_stmt)
    workspace_name = workspace_result.scalar()
    
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
        task_count=task_count,
        approval_count=approval_count,
        created_at=channel.created_at,
        updated_at=channel.updated_at
    )


# CSV bulk user addition endpoint - adds multiple users by uploading CSV file with email addresses
@router.post("/{channel_id}/members/bulk-csv", response_model=ChannelMemberList)
async def add_channel_members_bulk_csv(
    channel_id: str,
    request: Request,
    csv_file: UploadFile = File(..., description="CSV file with gmail_id and role columns"),
    platform_name: Optional[str] = Query(None, description="Platform name for email notifications (optional, defaults to config value)"),
    db: AsyncSession = Depends(get_db),
):
    """
    Grant access to multiple users for a channel by uploading a CSV file.
    
    This endpoint allows company admins or users with workspace management permissions to add multiple
    members to a channel by uploading a CSV file containing gmail_id and roles.
    
    CSV Format:
    gmail_id,role
    user1@gmail.com,Admin
    user2@gmail.com,User
    user3@gmail.com,User
    
    Required columns:
    - gmail_id: The Gmail address of the user
    - role: The role for the user in the channel (User or Admin, case-insensitive)
    
    The function will:
    1. Check if users already exist in the channel
    2. If users exist in DB but not in channel, add them directly
    3. If users don't exist in DB, return an error message
    
    Author: Pranhav Vimalbalaji
    Version: 1.0.0
    Last date modified: 13/08/2025
    """
    import csv
    import io
    from typing import List
    from datetime import datetime
    
    current_user = await get_current_user_required(request)

    # Validate channel_id as UUID
    channel_uuid = validate_uuid(channel_id, "channel ID")

    # Fetch channel
    stmt = select(Channel).where(Channel.id == channel_uuid)
    result = await db.execute(stmt)
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found")

    # Authorization: user must be company admin or able to manage within same company
    if not current_user.is_admin and str(current_user.company_id) != str(channel.company_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cross-company access denied")
    if not current_user.is_admin and not current_user.can_manage_workspace(str(channel.company_id)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    # Validate file type
    if not csv_file.filename or not csv_file.filename.lower().endswith('.csv'):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File must be a CSV file"
        )

    # Read CSV file content
    try:
        csv_content = await csv_file.read()
        csv_text = csv_content.decode('utf-8')
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid CSV file content"
        )

    # Parse CSV content
    try:
        csv_reader = csv.DictReader(io.StringIO(csv_text))
        
        # Validate required columns
        if 'gmail_id' not in csv_reader.fieldnames or 'role' not in csv_reader.fieldnames:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="CSV must contain 'gmail_id' and 'role' columns"
            )
        
        # Read and validate CSV data
        csv_data = []
        for row_num, row in enumerate(csv_reader, start=2):  # Start from 2 since row 1 is headers
            gmail_id = row.get('gmail_id', '').strip()
            role = row.get('role', '').strip()
            
            if not gmail_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Row {row_num}: gmail_id cannot be empty"
                )
            
            if not role:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Row {row_num}: role cannot be empty"
                )
            
            # Convert to lowercase for comparison, but accept any case variation
            role_lower = role.lower()
            if role_lower not in ['user', 'admin']:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Row {row_num}: role must be 'User' or 'Admin' (case-insensitive), got '{role}'"
                )
            
            csv_data.append((gmail_id, role))
            
    except csv.Error as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid CSV format: {str(e)}"
        )

    if not csv_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CSV file is empty or contains no valid data"
        )

    # Process users and track results
    created_members: List[ChannelMember] = []
    new_members: List[ChannelMember] = []  # Track only newly created members (not updated existing ones)
    errors: List[str] = []
    already_members: List[str] = []
    
    for gmail_id, role in csv_data:
        try:
            # Find user by email_id (gmail_id)
            user_stmt = select(User).where(
                and_(
                    User.email_id == gmail_id,
                    User.company_id == channel.company_id,
                    User.is_active == True
                )
            )
            user_result = await db.execute(user_stmt)
            user = user_result.scalar_one_or_none()
            
            if not user:
                # User doesn't exist in DB, return error as requested
                errors.append(f"Email ID '{gmail_id}' does not exist in the database")
                continue
                    
            # User exists in DB, check if already in channel
            existing_stmt = select(ChannelMember).where(
                and_(
                    ChannelMember.channel_id == channel.id,
                    ChannelMember.user_id == user.id
                )
            )
            existing_result = await db.execute(existing_stmt)
            existing = existing_result.scalar_one_or_none()
            
            if existing:
                # User already in channel, update role if different
                if existing.role != role:
                    existing.role = role
                    existing.updated_at = datetime.utcnow()
                    created_members.append(existing)
                else:
                    already_members.append(f"User {gmail_id} already in channel with {role} role")
            else:
                # User exists but not in channel, add them (this is a NEW member)
                member = ChannelMember(
                    id=generate_channel_id(),
                    channel_id=channel.id,
                    user_id=user.id,
                    role=role,
                    permissions={},  # Default permissions
                    is_active=True,
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )
                db.add(member)
                created_members.append(member)
                new_members.append(member)  # Track as new member for notifications
                
        except Exception as e:
            errors.append(f"Error processing user {gmail_id}: {str(e)}")
            continue

    # Commit all changes
    try:
        if created_members:
            await audit_log_write(db, current_user.id, "channel.members_bulk_added", "channel", channel.id, channel_id=channel.id, details={"count": len(created_members)})
        await db.commit()
        for member in created_members:
            await db.refresh(member)
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error while adding members: {str(e)}"
        )

    # Email: Accsell/Zaptag → requirement flow only (each added user gets email with View Channel); others → previous flow (notify channel admins)
    if new_members:
        try:
            new_member_user_ids = [member.user_id for member in new_members]
            new_member_users_stmt = select(User).where(User.id.in_(new_member_user_ids))
            new_member_users_result = await db.execute(new_member_users_stmt)
            new_member_users = {u.id: u for u in new_member_users_result.scalars().all()}
            # [DEBUG] Log query param and resolved value for bulk add (platform_name from query)
            platform_name_value = platform_name or settings.PLATFORM_NAME
            platform_lower = str(platform_name_value or '').strip().lower()
            print(f"📧 [channel bulk-add] platform_name param={platform_name!r}, resolved={platform_name_value!r}, platform_lower={platform_lower!r}, branch={'accsell/zaptag (to added user)' if platform_lower in ('accsell', 'zaptag') else 'admin (to admins)'}, new_members_count={len(new_members)}")
            if platform_lower in ('accsell', 'zaptag'):
                # Accsell/Zaptag: requirement flow only - send to each added user with "You have been added" + View Channel button
                for member in new_members:
                    user = new_member_users.get(member.user_id)
                    if user:
                        notification_data_user = {
                            'channel_id': str(channel.id),
                            'channel_name': channel.name,
                            'user_name': user.name or user.email_id.split('@')[0],
                            'user_email': user.email_id,
                            'user_role': member.role,
                            'added_by': current_user.name or current_user.email_id.split('@')[0],
                            'platform_name': platform_name_value,
                            'send_to_added_user': True
                        }
                        # View Channel URL: use SHAY_PLATFORM_URL when platform is Accsell and set, else PLATFORM_URL
                        base_url = (settings.SHAY_PLATFORM_URL or settings.PLATFORM_URL) if platform_lower == 'accsell' else settings.PLATFORM_URL
                        # [DEBUG] Confirm payload before calling email service (bulk)
                        print(f"📧 [channel bulk-add] Sending to added user: to_emails=[{user.email_id}], send_to_added_user={notification_data_user.get('send_to_added_user')!r}, platform_url={base_url!r}")
                        email_sent_user = email_service.send_channel_member_notification(
                            to_emails=[user.email_id],
                            notification_data=notification_data_user,
                            platform_url=base_url
                        )
                        if email_sent_user:
                            print(f"✅ Channel member notification (added user) sent to {user.email_id}")
                        else:
                            print(f"⚠️ Channel member notification (added user) failed to send")
            else:
                # Previous flow: send email notifications to channel admins (unchanged for non-Accsell/Zaptag; no send_to_added_user)
                print(f"📧 Preparing to notify channel admins about {len(new_members)} new member(s)...")
                channel_admins = await get_channel_admins(channel.id, db)
                if channel_admins:
                    admin_emails = [admin.email_id for admin in channel_admins if admin.email_id]
                    if admin_emails:
                        for member in new_members:
                            user = new_member_users.get(member.user_id)
                            if user:
                                # Do not add send_to_added_user here; email_service uses its absence for admin subject/body
                                notification_data = {
                                    'channel_name': channel.name,
                                    'user_name': user.name or user.email_id.split('@')[0],
                                    'user_email': user.email_id,
                                    'user_role': member.role,
                                    'added_by': current_user.name or current_user.email_id.split('@')[0],
                                    'platform_name': platform_name_value
                                }
                                email_sent = email_service.send_channel_member_notification(
                                    to_emails=admin_emails,
                                    notification_data=notification_data,
                                    platform_url=settings.PLATFORM_URL
                                )
                                if email_sent:
                                    print(f"✅ Channel member notification emails sent for {user.email_id}")
                                else:
                                    print(f"⚠️ Failed to send channel member notification emails for {user.email_id}")
                else:
                    print(f"ℹ️ No channel admins found to notify")
        except Exception as email_error:
            # Log email error but don't fail the member addition
            print(f"⚠️ Error sending channel member notifications (non-critical): {email_error}")
            import traceback
            print(f"📋 Email error traceback: {traceback.format_exc()}")

    # Prepare response
    items = [
        ChannelMemberResponse(
            id=str(m.id),
            channel_id=str(m.channel_id),
            user_id=str(m.user_id),
            role=m.role,
            is_active=m.is_active,
        )
        for m in created_members
    ]
    
    # Build comprehensive response message
    response_parts = []
    if created_members:
        response_parts.append(f"Successfully added {len(created_members)} members to the channel")
    if already_members:
        response_parts.append(f"{len(already_members)} users were already channel members")
    if errors:
        response_parts.append(f"{len(errors)} errors occurred during processing")
    
    response_message = ". ".join(response_parts) if response_parts else "No actions taken"
    
    return ChannelMemberList(
        items=items, 
        total=len(items),
        message=response_message,
        errors=errors if errors else None
    )


@router.delete("/{channel_id}")
async def delete_channel(
    channel_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Delete channel and all related data"""
    user = await get_current_user_required(request, db)
    
    # Validate channel_id as UUID
    channel_uuid = validate_uuid(channel_id, "channel ID")
    
    # Get channel
    stmt = select(Channel).where(Channel.id == channel_uuid)
    result = await db.execute(stmt)
    channel = result.scalar_one_or_none()
    
    if not channel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Channel not found"
        )
    
    # Check permissions
    if not channel.is_accessible_by_user(user.company_id, user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to channel"
        )
    
    try:
        await audit_log_write(db, user.id, "channel.deleted", "channel", channel_uuid, channel_id=channel_uuid)
        # Delete related records first (in order of dependencies)
        # Import models for deletion
        from app.models.message import Thread, Message
        from app.models.attachment import Attachment
        from app.models.task import Task
        
        # 1. Delete approvals first (they reference thread_id and message_id; no task_id)
        approvals_stmt = select(Approval).where(Approval.channel_id == channel_uuid)
        approvals_result = await db.execute(approvals_stmt)
        approvals = approvals_result.scalars().all()
        for approval in approvals:
            await db.delete(approval)
        
        # 2. Delete messages associated with this channel
        messages_stmt = select(Message).where(Message.channel_id == channel_uuid)
        messages_result = await db.execute(messages_stmt)
        messages = messages_result.scalars().all()
        
        for message in messages:
            await db.delete(message)
        
        # 3. Delete threads associated with this channel
        threads_stmt = select(Thread).where(Thread.channel_id == channel_uuid)
        threads_result = await db.execute(threads_stmt)
        threads = threads_result.scalars().all()
        
        for thread in threads:
            await db.delete(thread)
        
        # 4. Delete attachments associated with this channel
        attachments_stmt = select(Attachment).where(Attachment.channel_id == channel_uuid)
        attachments_result = await db.execute(attachments_stmt)
        attachments = attachments_result.scalars().all()
        
        for attachment in attachments:
            await db.delete(attachment)
        
        # 5. Delete tasks associated with this channel
        tasks_stmt = select(Task).where(Task.channel_id == channel_uuid)
        tasks_result = await db.execute(tasks_stmt)
        tasks = tasks_result.scalars().all()
        
        for task in tasks:
            await db.delete(task)
        
        # 6. Delete email_sync records that reference app_accounts before deleting app_accounts
        # First, get all app_account IDs for this channel
        app_accounts_stmt = select(AppAccount.id).where(AppAccount.channel_id == channel_uuid)
        app_accounts_result = await db.execute(app_accounts_stmt)
        app_account_ids = [row[0] for row in app_accounts_result.all()]
        
        # Delete email_sync records that reference these app_accounts
        if app_account_ids:
            # Use a simple approach: delete email_sync records for each app_account_id
            # This ensures proper foreign key constraint handling
            for app_account_id in app_account_ids:
                delete_email_sync_stmt = text(
                    "DELETE FROM gg_email_sync WHERE app_account_id = :app_account_id"
                )
                await db.execute(delete_email_sync_stmt, {'app_account_id': app_account_id})
                
                # Delete message_sync records
                delete_message_sync_stmt = text(
                    "DELETE FROM gg_message_sync WHERE app_account_id = :app_account_id"
                )
                await db.execute(delete_message_sync_stmt, {'app_account_id': app_account_id})
            
            # Flush to ensure sync records are deleted before app_accounts deletion
            await db.flush()
        
        # 7. Delete app accounts connected to this channel
        app_accounts_stmt = select(AppAccount).where(AppAccount.channel_id == channel_uuid)
        app_accounts_result = await db.execute(app_accounts_stmt)
        app_accounts = app_accounts_result.scalars().all()
        
        for app_account in app_accounts:
            await db.delete(app_account)
        
        # 8. Delete data sources associated with this channel
        datasources_stmt = select(Datasource).where(Datasource.channel_id == channel_uuid)
        datasources_result = await db.execute(datasources_stmt)
        datasources = datasources_result.scalars().all()
        
        for datasource in datasources:
            await db.delete(datasource)
        
        # 9. Delete channel members
        # Use direct SQL delete for channel members to ensure it works
        
        # First, let's see how many members exist
        members_count_stmt = select(func.count(ChannelMember.id)).where(ChannelMember.channel_id == channel_uuid)
        members_count_result = await db.execute(members_count_stmt)
        members_count = members_count_result.scalar()
        print(f"Found {members_count} channel members to delete for channel {channel_uuid}")
        
        # Delete all channel members using direct SQL delete
        delete_members_stmt = delete(ChannelMember).where(ChannelMember.channel_id == channel_uuid)
        members_delete_result = await db.execute(delete_members_stmt)
        print(f"Deleted {members_delete_result.rowcount} channel members")
        
        # Force flush to ensure the deletes are applied
        await db.flush()
        
        # 9. Finally delete the channel itself
        await db.delete(channel)
        
        # Commit all changes
        await db.commit()
        
        return {"message": "Channel and all related data deleted successfully"}
        
    except Exception as e:
        await db.rollback()
        print(f"Error during channel deletion: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting channel: {str(e)}"
        ) 
