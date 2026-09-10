"""
move_thread sub-step: apply the cross-table channel_id cascade update for a
thread move (threads, messages, email_attachments, attachments,
shortened_urls).

Split out of app/routes/messages/threads_move.py — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, wave B2.
"""

from datetime import datetime
from typing import Dict

from sqlalchemy import select, update
from sqlalchemy.sql import func as sa_func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.message import Message, Thread
from app.models.attachment import Attachment
from app.models.email_attachment import EmailAttachment
from app.models.shortened_url import ShortenedUrl


async def apply_thread_move_cascade(
    db: AsyncSession, thread_id, old_channel_id, new_channel_id
) -> Dict[str, int]:
    """Update every table referencing this thread/channel to point at the
    new channel. Returns a dict of table_name -> rows updated.

    Does not commit or roll back — the caller owns the transaction so audit
    logging can happen inside the same commit.
    """
    updated_counts: Dict[str, int] = {}

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

    return updated_counts
