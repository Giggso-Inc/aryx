"""
POST /threads — create_thread.

Split out of the original app/routes/messages.py (2,513 lines) — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5.

Wave B2: POST /threads/by-phone (get_or_create_thread_by_phone) split out
to its own sibling file, threads_by_phone.py.
"""

from fastapi import APIRouter, HTTPException, status, Request, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.auth import generate_workspace_id
from app.middleware.auth_middleware import get_current_user_required
from app.services.audit_service import log as audit_log_write
from app.models.channel import Channel
from app.models.message import Thread
from app.schemas.message import ThreadCreate, ThreadResponse
from .socket_events import emit_thread_created_event

router = APIRouter()


@router.post("/threads", response_model=ThreadResponse)
async def create_thread(
    thread_data: ThreadCreate,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> ThreadResponse:
    """Create a new thread"""
    user = await get_current_user_required(request)

    # Get channel
    stmt = select(Channel).where(Channel.id == thread_data.channel_id)
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

    # Create thread
    thread = Thread(
        id=generate_workspace_id(),  # Reusing workspace ID generator for thread
        title=thread_data.title,
        description=thread_data.description,
        channel_id=thread_data.channel_id,
        ai_enabled=channel.ai_enabled  # Inherit AI settings from channel
    )

    db.add(thread)
    await audit_log_write(db, user.id, "thread.created", "thread", thread.id, channel_id=thread.channel_id, thread_id=thread.id)
    await db.commit()
    await db.refresh(thread)

    # Convert UUID fields to strings for response
    # Prepare response data
    response = ThreadResponse(
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
        created_at=thread.created_at,
        updated_at=thread.updated_at
    )

    # Emit socket event at the END - PURE EMISSION ONLY
    await emit_thread_created_event(
        channel_id=str(thread.channel_id),
        thread_id=str(thread.id)
    )

    return response
