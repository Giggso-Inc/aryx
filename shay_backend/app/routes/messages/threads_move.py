"""
POST /threads/move — move_thread: move a thread between two regular
(message-type) channels in the same workspace.

Split out of the original app/routes/messages.py (2,513 lines) — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5.
"""

from datetime import datetime

from fastapi import APIRouter, HTTPException, status, Request, Depends
from sqlalchemy import select, update
from sqlalchemy.sql import func as sa_func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.services.audit_service import log as audit_log_write
from app.models.channel import Channel
from app.models.message import Message, Thread
from app.models.attachment import Attachment
from app.models.email_attachment import EmailAttachment
from app.models.shortened_url import ShortenedUrl
from app.schemas.message import ThreadMoveRequest, ThreadMoveResponse

router = APIRouter()


@router.post("/threads/move", response_model=ThreadMoveResponse)
async def move_thread(
    payload: ThreadMoveRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ThreadMoveResponse:
    """
    Move a thread from one regular channel to another. Both channels must be
    message-type; validations include same workspace and active thread.
    """
    # Require authenticated user (avoids Depends(get_current_user) which triggers FastAPI response-field error on AsyncSession)
    user = await get_current_user_required(request, db)

    thread_id = payload.thread_id

    # A. Load and validate the thread
    stmt = select(Thread).where(Thread.id == thread_id)
    result = await db.execute(stmt)
    thread = result.scalar_one_or_none()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    old_channel_id = thread.channel_id
    if old_channel_id == payload.new_channel_id:
        raise HTTPException(status_code=400, detail="Thread is already in this channel")

    # B. Validate both channels exist and are regular (message-type)
    stmt_src = select(Channel).where(Channel.id == old_channel_id)
    result_src = await db.execute(stmt_src)
    source_channel = result_src.scalar_one_or_none()
    stmt_dest = select(Channel).where(Channel.id == payload.new_channel_id)
    result_dest = await db.execute(stmt_dest)
    dest_channel = result_dest.scalar_one_or_none()
    if not source_channel or not dest_channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    # Regular channel = "message" type (DB may store as string "message" or integer 1)
    def _is_message_channel(ch) -> bool:
        if ch.channel_type is None:
            return False
        s = str(ch.channel_type).lower()
        return s == "message" or (isinstance(ch.channel_type, int) and ch.channel_type == 1)

    if not _is_message_channel(source_channel) or not _is_message_channel(dest_channel):
        raise HTTPException(
            status_code=400,
            detail="Thread moves are only allowed between regular (message-type) channels",
        )
    if source_channel.workspace_id != dest_channel.workspace_id:
        raise HTTPException(status_code=400, detail="Cannot move thread across workspaces")

    # Permission: caller must have access to source channel
    if not source_channel.is_accessible_by_user(str(user.company_id), user.role or ""):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to source channel",
        )

    # C. Validate thread is active
    if not thread.is_active or thread.is_archived:
        raise HTTPException(
            status_code=400,
            detail="Only active, non-archived threads can be moved",
        )

    updated_counts = {}
    new_channel_id = payload.new_channel_id

    try:
        # D1. gg_threads
        stmt = (
            update(Thread)
            .where(Thread.id == thread_id)
            .values(channel_id=new_channel_id, updated_at=datetime.utcnow())
        )
        r = await db.execute(stmt)
        updated_counts["gg_threads"] = r.rowcount or 0

        # D2. gg_messages
        stmt = (
            update(Message)
            .where(Message.thread_id == thread_id)
            .values(updated_at=datetime.utcnow())
        )
        r = await db.execute(stmt)
        updated_counts["gg_messages"] = r.rowcount or 0

        # D3. gg_approvals — no thread_id or channel_id columns; linked only via message_id
        updated_counts["gg_approvals"] = 0

        # D4. gg_tasks — no thread_id or channel_id columns; linked only via message_id
        updated_counts["gg_tasks"] = 0

        # D5. gg_email_attachments
        stmt = (
            update(EmailAttachment)
            .where(EmailAttachment.thread_id == thread_id, EmailAttachment.channel_id == old_channel_id)
            .values(channel_id=new_channel_id, updated_at=datetime.utcnow())
        )
        r = await db.execute(stmt)
        updated_counts["gg_email_attachments"] = r.rowcount or 0

        # D6. gg_attachments (no thread_id; link via message_id)
        msg_subq = select(Message.id).where(Message.thread_id == thread_id)
        stmt = (
            update(Attachment)
            .where(
                Attachment.channel_id == old_channel_id,
                Attachment.message_id.in_(msg_subq),
            )
            .values(channel_id=new_channel_id, updated_at=datetime.utcnow())
        )
        r = await db.execute(stmt)
        updated_counts["gg_attachments"] = r.rowcount or 0

        # D7. gg_shortened_urls — replace old path with new path in original_url; update optional columns when present
        old_path = f"/threads/{old_channel_id}/{thread_id}"
        new_path = f"/threads/{new_channel_id}/{thread_id}"
        stmt = (
            update(ShortenedUrl)
            .where(ShortenedUrl.original_url.contains(old_path))
            .values(
                original_url=sa_func.replace(ShortenedUrl.original_url, old_path, new_path),
                thread_id=thread_id,
                channel_id=new_channel_id,
                last_updated_at=datetime.utcnow(),
            )
        )
        r = await db.execute(stmt)
        updated_counts["gg_shortened_urls"] = r.rowcount or 0

        await audit_log_write(db, user.id, "thread.moved", "thread", thread.id, channel_id=new_channel_id, thread_id=thread.id, details={"old_channel_id": str(old_channel_id), "new_channel_id": str(new_channel_id)})
        await db.commit()
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

    return ThreadMoveResponse(
        thread_id=payload.thread_id,
        old_channel_id=old_channel_id,
        new_channel_id=payload.new_channel_id,
        updated_counts=updated_counts,
    )
