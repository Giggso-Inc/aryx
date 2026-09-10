"""
DELETE /threads/{thread_id} — delete_thread: admin-only cascading thread
delete (messages, AI responses, and — for email channels — the related
gg_email_* tables).

Split out of the original app/routes/messages.py (2,513 lines) — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5.

Wave B2 follow-up: the Phase-5 file kept the email-channel branch inline
under a "stated exception" (shared thread/channel objects). Re-examined:
the email cleanup only needs thread_id and the channel object as explicit
inputs, so it splits cleanly into:
  - threads_delete_lookup: thread/channel fetch, permission checks
  - threads_delete_email_cleanup: email-channel detection + gg_email_* cleanup
  - threads_delete_cascade: message + AI-response deletion
This orchestrator still owns the overall delete sequence and the single
commit at the end.
"""

from fastapi import APIRouter, Request, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.services.audit_service import log as audit_log_write
from app.models.message import Message
from .threads_delete_lookup import get_thread_or_404, get_channel_or_404, check_delete_thread_permissions
from .threads_delete_email_cleanup import is_email_channel, cleanup_email_thread_data
from .threads_delete_cascade import delete_thread_messages, delete_thread_ai_responses

router = APIRouter()


@router.delete("/threads/{thread_id}")
async def delete_thread(
    thread_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> dict:
    """Delete a thread and all its messages"""
    user = await get_current_user_required(request)

    thread = await get_thread_or_404(db, thread_id)
    channel = await get_channel_or_404(db, thread.channel_id)
    check_delete_thread_permissions(channel, user)

    # Get message count for confirmation
    message_count_query = select(func.count(Message.id)).where(Message.thread_id == thread_id)
    message_count_result = await db.execute(message_count_query)
    message_count = message_count_result.scalar()

    await audit_log_write(db, user.id, "thread.deleted", "thread", thread.id, channel_id=thread.channel_id, thread_id=thread.id)

    # 1. gg_messages
    await delete_thread_messages(db, thread_id)

    # 2–5. Email-related tables: only for email channels; single txn, no swallowed exceptions
    if await is_email_channel(db, channel):
        await cleanup_email_thread_data(db, thread.id)

    # 6. gg_ai_responses
    ai_responses = await delete_thread_ai_responses(db, thread_id)

    # 7. gg_threads – delete the thread row last
    await db.delete(thread)

    await db.commit()

    return {
        "message": "Thread deleted successfully",
        "thread_id": thread_id,
        "deleted_messages": message_count,
        "deleted_ai_responses": len(ai_responses)
    }
