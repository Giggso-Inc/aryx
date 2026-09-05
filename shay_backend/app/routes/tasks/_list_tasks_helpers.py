"""
Private helpers for list_tasks.py (GET /), extracted so the endpoint's own
handler body stays under the 150-line-per-file target. Not part of the
package's public router surface and not reused by any other endpoint.
"""

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, desc
from sqlalchemy.sql.expression import literal
from sqlalchemy.dialects.postgresql import JSONB as PgJSONB

from app.utils.channel_access import check_channel_access_by_thread
from app.models.task import Task
from app.models.channel_member import ChannelMember
from app.models.message import Message


async def get_user_channel_ids(db: AsyncSession, user) -> list:
    """Channels where the user is a member (active channels only)."""
    user_channels_query = select(ChannelMember.channel_id).where(
        and_(
            ChannelMember.user_id == user.id,
            ChannelMember.is_active == True
        )
    )
    user_channels_result = await db.execute(user_channels_query)
    user_channel_ids = [str(c) for c in user_channels_result.scalars().all()]
    print(f"User {user.id} is a member of {len(user_channel_ids)} active channels")
    print(f"Channel IDs: {user_channel_ids}")
    return user_channel_ids


async def get_visible_message_ids(
    db: AsyncSession, user, user_channel_ids: list,
    thread_id: Optional[str], channel_id: Optional[str],
) -> list:
    """Message IDs visible to the user (messages in their channels)."""
    user_messages_query = select(Message.id).where(
        Message.channel_id.in_(user_channel_ids)
    )
    if thread_id:
        # Check channel access via thread_id before filtering
        await check_channel_access_by_thread(db, user, thread_id)
        user_messages_query = user_messages_query.where(Message.thread_id == thread_id)
    if channel_id:
        user_messages_query = user_messages_query.where(Message.channel_id == channel_id)

    user_messages_result = await db.execute(user_messages_query)
    return [row[0] for row in user_messages_result.all()]


def build_filter_conditions(
    visible_message_ids: list, status: Optional[str], priority: Optional[str],
    assigned_to: Optional[str], source: Optional[str], tags: Optional[str],
    created_by: Optional[str],
) -> list:
    """Build the base_conditions list applied to the task query."""
    base_conditions = [Task.message_id.in_(visible_message_ids)]

    if status:
        status_list = [s.strip() for s in status.split(",") if s.strip()]
        if status_list:
            base_conditions.append(Task.status.in_(status_list))

    if priority:
        base_conditions.append(Task.priority == priority)

    if assigned_to:
        base_conditions.append(Task.assigned_to == assigned_to)

    if source:
        base_conditions.append(Task.source == source)

    if created_by:
        base_conditions.append(Task.created_by == created_by)

    if tags:
        tag_list = [tag.strip() for tag in tags.split(",")]
        base_conditions.append(Task.tags.op("@>")(literal(tag_list, type_=PgJSONB())))

    return base_conditions


