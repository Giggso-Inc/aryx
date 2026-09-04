"""
Channel creation endpoint.

Split out of the original app/routes/channels.py (2,630 lines) — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5.
"""

from datetime import datetime

from fastapi import APIRouter, HTTPException, status, Request, Depends
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.auth import generate_channel_id, generate_workspace_id
from app.middleware.auth_middleware import get_current_user_required
from app.models.channel import Channel
from app.models.workspace import Workspace
from app.models.channel_member import ChannelMember
from app.services.audit_service import log as audit_log_write
from app.schemas.channel import ChannelCreate, ChannelResponse

router = APIRouter()


@router.post("/", response_model=ChannelResponse)
async def create_channel(
    channel_data: ChannelCreate,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> ChannelResponse:
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
