"""
GET /count endpoint (mounted at /api/v1/tasks): get_task_count.

Split out of the former listing.py (part of the Phase 5a item 2 follow-up
that lowered the per-file target to 150 lines). Must be registered before
detail.py's dynamic `GET /{task_id}` route (see app/routes/tasks/__init__.py)
so this literal `/count` path isn't swallowed as task_id="count".
"""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.task import Task
from app.models.channel_member import ChannelMember
from app.models.message import Message
from app.schemas.task import TaskCountResponse

router = APIRouter()


@router.get("/count", response_model=TaskCountResponse)
async def get_task_count(
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> TaskCountResponse:
    """Get total count of tasks for the current user - uses same logic as list endpoint"""
    user = await get_current_user_required(request, db)

    # Get channels where the user is a member (active channels only)
    user_channels_query = select(ChannelMember.channel_id).where(
        and_(
            ChannelMember.user_id == user.id,
            ChannelMember.is_active == True
        )
    )

    user_channels_result = await db.execute(user_channels_query)
    user_channel_ids = [str(c) for c in user_channels_result.scalars().all()]

    if not user_channel_ids:
        return TaskCountResponse(task_count=0)

    # Use the same logic as list_tasks endpoint:
    # Count tasks linked to messages in user's channels.
    visible_message_ids_query = select(Message.id).where(
        Message.channel_id.in_(user_channel_ids)
    )
    visible_msg_result = await db.execute(visible_message_ids_query)
    visible_message_ids = [row[0] for row in visible_msg_result.all()]

    if not visible_message_ids:
        return TaskCountResponse(task_count=0)

    count_query = select(func.count(Task.id)).where(
        Task.message_id.in_(visible_message_ids)
    )
    count_result = await db.execute(count_query)
    total_count = count_result.scalar() or 0

    return TaskCountResponse(task_count=total_count)
