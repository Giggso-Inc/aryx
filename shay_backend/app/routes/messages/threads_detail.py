"""
GET /threads/{thread_id} — get_thread_details.

Split out of app/routes/messages/threads_list.py — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, wave B2.

Registration order note: this is a 2-segment literal-prefixed path
("/threads/{thread_id}"), so it does not compete with the single-segment
dynamic GET /{thread_id} in messages_read_thread.py; still registered
right after threads_list to keep the original file's endpoint order.
"""

from fastapi import APIRouter, HTTPException, status, Request, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.channel import Channel
from app.models.message import Thread
from app.schemas.message import ThreadResponse
from .threads_first_message import get_first_message_id

router = APIRouter()


@router.get("/threads/{thread_id}", response_model=ThreadResponse)
async def get_thread_details(
    thread_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> ThreadResponse:
    """Get thread details by thread ID"""
    user = await get_current_user_required(request)

    # Get thread
    stmt = select(Thread).where(Thread.id == thread_id)
    result = await db.execute(stmt)
    thread = result.scalar_one_or_none()

    if not thread:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Thread not found"
        )

    # Get channel
    stmt = select(Channel).where(Channel.id == thread.channel_id)
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

    first_message_id = await get_first_message_id(db, thread.id)

    # Return thread details in the same structure as ThreadResponse
    return ThreadResponse(
        id=str(thread.id),
        title=thread.title,
        description=thread.description,
        channel_id=str(thread.channel_id),
        is_active=thread.is_active,
        is_archived=thread.is_archived,
        message_count=thread.message_count,
        last_message_at=thread.last_message_at,
        ai_enabled=thread.ai_enabled,
        ai_summary=thread.ai_summary,
        first_message_id=first_message_id,
        created_at=thread.created_at,
        updated_at=thread.updated_at
    )
