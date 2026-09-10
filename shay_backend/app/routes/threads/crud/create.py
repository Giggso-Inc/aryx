"""
POST / (create_thread) — mounted at /api/v1/threads.

Split from app/routes/threads/crud.py (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.auth import generate_workspace_id
from app.middleware.auth_middleware import get_current_user_required
from app.models.channel import Channel
from app.models.message import Thread
from app.schemas.message import ThreadCreate, ThreadResponse

from .serializers import thread_to_response

router = APIRouter()


@router.post("/", response_model=ThreadResponse, status_code=201)
async def create_thread(
    thread_data: ThreadCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ThreadResponse:
    """Create a new thread in a channel."""
    user = await get_current_user_required(request, db)

    try:
        channel_uuid = UUID(thread_data.channel_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid channel_id format")

    channel = (await db.execute(select(Channel).where(Channel.id == channel_uuid))).scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    if not channel.is_accessible_by_user(str(user.company_id), user.role):
        raise HTTPException(status_code=403, detail="Access denied to channel")

    thread = Thread(
        id=generate_workspace_id(),
        title=thread_data.title,
        description=thread_data.description,
        channel_id=channel_uuid,
        ai_enabled=channel.ai_enabled,
    )
    db.add(thread)
    await db.commit()
    await db.refresh(thread)

    return thread_to_response(thread)
