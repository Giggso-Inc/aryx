"""
PUT /{channel_id} and DELETE /{channel_id} — single-channel write endpoints
(update and cascading delete).

Split out of the original app/routes/channels.py (2,630 lines) — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5.
"""

from datetime import datetime

from fastapi import APIRouter, HTTPException, status, Request, Depends
from sqlalchemy import select, func, and_, delete, text
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


@router.delete("/{channel_id}")
async def delete_channel(
    channel_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> dict:
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
