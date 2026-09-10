"""
Row-building helper for the datasource list endpoint's response.

Private module: used only by list_datasources.py. Extracted verbatim from
the endpoint so the per-row channel/user lookups and dict-building can live
in their own file, keeping the endpoint function itself under the line cap.
"""

import uuid
from typing import Any, Dict, List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.channel import Channel
from app.models.datasource import Datasource
from app.models.user import User

from ._metadata_helpers import sanitize_datasource_metadata


async def fetch_channel_membership_map(db: AsyncSession, user, datasources) -> Dict[Any, Any]:
    """Fetch the current user's channel memberships for all channels in this page (avoids N+1)."""
    from sqlalchemy import and_
    from app.models.channel_member import ChannelMember

    unique_channel_ids = list({ds.channel_id for ds in datasources if ds.channel_id})
    members_map = {}
    if unique_channel_ids:
        members_stmt = select(ChannelMember).where(
            and_(
                ChannelMember.channel_id.in_(unique_channel_ids),
                ChannelMember.user_id == user.id,
                ChannelMember.is_active == True
            )
        )
        members_result = await db.execute(members_stmt)
        for member in members_result.scalars().all():
            members_map[member.channel_id] = member
    return members_map


async def build_datasource_list_rows(
    datasources, members_map: Dict[Any, Any], db: AsyncSession
) -> List[Dict[str, Any]]:
    """Convert ORM datasource rows into the response dict shape, with channel/user detail."""
    datasource_responses = []
    for datasource in datasources:
        # Get channel for workspace_id and company_id
        channel_stmt = select(Channel).where(Channel.id == datasource.channel_id)
        channel_result = await db.execute(channel_stmt)
        channel = channel_result.scalar_one_or_none()

        # Get user who added the datasource
        added_by_user = None
        if datasource.added_by:
            # Ensure added_by is a UUID object if it's a string
            added_by_id = datasource.added_by
            if isinstance(added_by_id, str):
                try:
                    added_by_id = uuid.UUID(added_by_id)
                except (ValueError, AttributeError):
                    added_by_id = None

            if added_by_id:
                user_stmt = select(User).where(User.id == added_by_id)
                user_result = await db.execute(user_stmt)
                added_by_user = user_result.scalar_one_or_none()

        # Convert channel to dict (include is_member and member_role from gg_channel_members)
        channel_dict = None
        if channel:
            member = members_map.get(channel.id)
            is_member = member is not None
            # member_role: "admin" or "user" per gg_channel_members.role
            member_role = ("admin" if member.role == "admin" else "user") if member else None
            channel_dict = {
                "id": str(channel.id),
                "name": channel.name,
                "description": channel.description,
                "workspace_id": str(channel.workspace_id),
                "workspace_name": getattr(channel, 'workspace_name', None),
                "company_id": str(channel.company_id),
                "is_active": channel.is_active,
                "is_public": channel.is_public,
                "ai_enabled": channel.ai_enabled,
                "channel_settings": channel.channel_settings,
                "message_count": getattr(channel, 'message_count', 0),
                "last_message_at": getattr(channel, 'last_message_at', None),
                "created_at": channel.created_at,
                "updated_at": channel.updated_at,
                "is_member": is_member,
                "member_role": member_role
            }

        # Convert user to dict
        user_dict = None
        if added_by_user:
            user_dict = {
                "user_id": str(added_by_user.id),
                "name": added_by_user.name,
                "email_id": added_by_user.email_id,
                "avatar_url": added_by_user.avatar_url,
                "company_id": str(added_by_user.company_id),
                "role": added_by_user.role,
                "created_datetime": added_by_user.created_datetime,
                "updated_datetime": added_by_user.updated_datetime
            }

        datasource_responses.append({
            "id": str(datasource.id),
            "name": datasource.name,
            "filename": datasource.filename,
            "storage_type": datasource.storage_type,
            "provider": datasource.provider,
            "app_type": datasource.app_type,
            "config": datasource.config,
            "datasource_metadata": sanitize_datasource_metadata(datasource.datasource_metadata),
            "giggso_vault_id": str(datasource.giggso_vault_id) if datasource.giggso_vault_id else None,
            "file_size": datasource.file_size,
            "file_type": datasource.file_type,
            "file_url": datasource.file_url,
            "channel": channel_dict,  # Full channel object as dict
            "added_by_user": user_dict,  # Full user object as dict
            "is_active": datasource.is_active,
            "is_connected": datasource.is_connected,
            "is_processed": datasource.is_processed,
            "processing_status": datasource.processing_status,
            "error_message": datasource.error_message,
            "last_processed_at": datasource.last_processed_at,
            "processing_time": datasource.processing_time,
            "record_count": datasource.record_count,
            "is_embedding_required": datasource.is_embedding_required,
            "embedding_status": datasource.embedding_status,
            "created_at": datasource.created_at,
            "updated_at": datasource.updated_at
        })
    return datasource_responses
