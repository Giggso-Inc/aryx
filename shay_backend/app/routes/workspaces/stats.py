"""
Workspace statistics endpoint.

Split from app/routes/workspaces.py (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2).
"""

from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.schemas.workspace import WorkspaceStats
from app.utils.permissions import require_active_workspace_role

from .helpers import _get_workspace_or_404

router = APIRouter()


@router.get("/{workspace_id}/stats", response_model=WorkspaceStats)
async def get_workspace_stats(
    workspace_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> WorkspaceStats:
    """Get workspace statistics"""
    user = await get_current_user_required(request)
    workspace = await _get_workspace_or_404(db, workspace_id)
    workspace_uuid = UUID(str(workspace.id))

    # Check access permissions
    await require_active_workspace_role(db, user.id, workspace_uuid)

    # Get statistics (simplified for now)
    from app.models.message import Message, Thread
    from app.models.channel import Channel
    from app.models.attachment import Attachment
    from app.models.ai_response import AIResponse

    # Subquery: channel IDs belonging to this workspace
    channel_subq = select(Channel.id).where(Channel.workspace_id == workspace_uuid).scalar_subquery()

    # Count threads via channel chain (gg_threads has no workspace_id)
    thread_count = await db.execute(select(func.count(Thread.id)).where(Thread.channel_id.in_(channel_subq)))
    total_threads = thread_count.scalar()

    # Subquery: thread IDs belonging to channels in this workspace
    thread_subq = select(Thread.id).where(Thread.channel_id.in_(channel_subq)).scalar_subquery()

    # Count messages via thread chain (gg_messages has no workspace_id)
    msg_count = await db.execute(select(func.count(Message.id)).where(Message.thread_id.in_(thread_subq)))
    total_messages = msg_count.scalar()

    # Count attachments
    attach_count = await db.execute(select(func.count(Attachment.id)).where(Attachment.workspace_id == workspace_uuid))
    total_attachments = attach_count.scalar()

    # Count AI responses
    ai_count = await db.execute(select(func.count(AIResponse.id)).where(AIResponse.workspace_id == workspace_uuid))
    ai_responses_count = ai_count.scalar()

    return WorkspaceStats(
        workspace_id=workspace_id,
        total_messages=total_messages,
        total_threads=total_threads,
        total_attachments=total_attachments,
        ai_responses_count=ai_responses_count,
        last_activity=None  # TODO: Implement last activity calculation
    )
