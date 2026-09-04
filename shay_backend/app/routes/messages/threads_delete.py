"""
DELETE /threads/{thread_id} — delete_thread: admin-only cascading thread
delete (messages, AI responses, and — for email channels — the related
gg_email_* tables).

Split out of the original app/routes/messages.py (2,513 lines) — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5.

Stated exception: kept as one file rather than split further. The
email-channel branch reuses `thread`/`channel` loaded at the top and its
several raw-SQL cleanup statements are one coherent "is this an email
thread" decision tree — splitting it out would mean passing that decision
and the loaded objects across module boundaries for no real readability
gain.
"""

import logging

from fastapi import APIRouter, HTTPException, status, Request, Depends
from sqlalchemy import select, func, and_, text, bindparam
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.services.audit_service import log as audit_log_write
from app.models.channel import Channel
from app.models.app_account import AppAccount
from app.models.message import Message, Thread
from app.models.ai_response import AIResponse

logger = logging.getLogger(__name__)
router = APIRouter()


@router.delete("/threads/{thread_id}")
async def delete_thread(
    thread_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> dict:
    """Delete a thread and all its messages"""
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

    # Check if user has admin role for deletion
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can delete threads"
        )

    # Get message count for confirmation
    message_count_query = select(func.count(Message.id)).where(Message.thread_id == thread_id)
    message_count_result = await db.execute(message_count_query)
    message_count = message_count_result.scalar()

    await audit_log_write(db, user.id, "thread.deleted", "thread", thread.id, channel_id=thread.channel_id, thread_id=thread.id)
    # 1. gg_messages – delete so they don’t point at a missing thread
    delete_messages_stmt = select(Message).where(Message.thread_id == thread_id)
    messages_result = await db.execute(delete_messages_stmt)
    messages = messages_result.scalars().all()
    for message in messages:
        await db.delete(message)
    # 2–5. Email-related tables: only for email channels; single txn, no swallowed exceptions
    is_email_channel = (
        channel.channel_type is not None
        and str(channel.channel_type).strip().lower() == "email"
    )
    if not is_email_channel:
        # Fallback: treat as email channel if this channel has an active email AppAccount
        email_acct = await db.execute(
            select(AppAccount).where(
                and_(
                    AppAccount.channel_id == channel.id,
                    AppAccount.api_key == "email",
                    AppAccount.is_active == True,
                )
            ).limit(1)
        )
        is_email_channel = email_acct.scalar_one_or_none() is not None
    if is_email_channel:
        # Use thread.id (UUID) so WHERE thread_id = :tid matches DB column type
        tid_uuid = thread.id
        # Get email_ids for this thread before we clear gg_emails.thread_id (for gg_email_hash fallback)
        email_ids_result = await db.execute(
            text("SELECT email_id FROM gg_emails WHERE thread_id = :tid"),
            {"tid": tid_uuid},
        )
        thread_email_ids = [row[0] for row in email_ids_result.fetchall() if row and row[0]]
        # 2. gg_email_attachments – DELETE where thread_id = <thread_id>
        await db.execute(text("DELETE FROM gg_email_attachments WHERE thread_id = :tid"), {"tid": tid_uuid})
        # 3. gg_case_id – DELETE where thread_id = <thread_id>
        await db.execute(text("DELETE FROM gg_case_id WHERE thread_id = :tid"), {"tid": tid_uuid})
        # 4. gg_emails – unlink and clear ml_processed_at only; leave thread_created true so scheduler doesn’t treat as “needs thread”
        r_emails = await db.execute(
            text("UPDATE gg_emails SET thread_id = NULL, ml_processed_at = NULL WHERE thread_id = :tid"),
            {"tid": tid_uuid},
        )
        emails_updated = getattr(r_emails, "rowcount", None)
        if emails_updated is not None and emails_updated == 0:
            logger.warning("delete_thread: gg_emails UPDATE matched 0 rows for thread_id=%s", thread_id)
        else:
            logger.debug("delete_thread: gg_emails updated %s rows for thread_id=%s", emails_updated, thread_id)
        # 5. gg_email_hash – unlink and clear ml_processed (by thread_id; fallback by email_id if 0 rows)
        r_hash = await db.execute(
            text("UPDATE gg_email_hash SET thread_id = NULL, ml_processed = false WHERE thread_id = :tid"),
            {"tid": tid_uuid},
        )
        hash_updated = getattr(r_hash, "rowcount", None)
        if hash_updated is not None and hash_updated == 0 and thread_email_ids:
            # Fallback: table may link by email_id only; update by this thread’s email_ids
            stmt_hash_by_email = text(
                "UPDATE gg_email_hash SET thread_id = NULL, ml_processed = false WHERE email_id IN :email_ids"
            ).bindparams(bindparam("email_ids", expanding=True))
            r_hash2 = await db.execute(stmt_hash_by_email, {"email_ids": thread_email_ids})
            hash_updated = getattr(r_hash2, "rowcount", None)
            logger.debug("delete_thread: gg_email_hash fallback by email_id updated %s rows for thread_id=%s", hash_updated, thread_id)
        if hash_updated is not None and hash_updated == 0:
            logger.warning("delete_thread: gg_email_hash UPDATE matched 0 rows for thread_id=%s", thread_id)
        else:
            logger.debug("delete_thread: gg_email_hash updated %s rows for thread_id=%s", hash_updated, thread_id)
    else:
        # Not an email channel; skip gg_email_* cleanup (only gg_messages, gg_ai_responses, gg_threads are deleted)
        logger.debug("delete_thread: non-email channel, skipping gg_emails/gg_email_hash cleanup for thread_id=%s", thread_id)
    # 6. gg_ai_responses
    ai_responses_stmt = select(AIResponse).where(AIResponse.thread_id == thread_id)
    ai_responses_result = await db.execute(ai_responses_stmt)
    ai_responses = ai_responses_result.scalars().all()
    for ai_response in ai_responses:
        await db.delete(ai_response)
    # 7. gg_threads – delete the thread row last
    await db.delete(thread)

    await db.commit()

    return {
        "message": "Thread deleted successfully",
        "thread_id": thread_id,
        "deleted_messages": message_count,
        "deleted_ai_responses": len(ai_responses)
    }
