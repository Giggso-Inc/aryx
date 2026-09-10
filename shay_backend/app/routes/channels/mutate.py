"""
PUT /{channel_id} — update_channel: single-channel update endpoint.

Split out of the original app/routes/channels.py (2,630 lines) — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5.

DELETE /{channel_id} (delete_channel) was further split out to
mutate_delete.py in wave B3 to bring this file under 150 lines.
"""

from fastapi import APIRouter, HTTPException, status, Request, Depends
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.channel import Channel
from app.models.workspace import Workspace
from app.models.task import Task
from app.models.approval import Approval
from app.services.audit_service import log as audit_log_write
from app.schemas.channel import ChannelUpdate, ChannelResponse
from .helpers import validate_uuid

router = APIRouter()


@router.put("/{channel_id}", response_model=ChannelResponse)
async def update_channel(
    channel_id: str,
    channel_data: ChannelUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> ChannelResponse:
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


