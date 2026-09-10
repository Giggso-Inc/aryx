"""
create_message sub-step: bump thread/channel counters, write the audit
log entry, commit, and refresh the new message.

Split out of app/routes/messages/messages_create.py — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, wave B2.

NOTE: tests/test_messages_characterization.py patches
`app.routes.messages.messages_create_persist.audit_log_write` — keep this
import name stable if this file moves again.
"""

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.channel import Channel
from app.models.message import Message, Thread
from app.services.audit_service import log as audit_log_write


async def persist_new_message(
    db: AsyncSession,
    message: Message,
    thread: Thread,
    channel: Channel,
    user_id,
    message_type: str,
) -> None:
    """Update thread/channel metadata, audit-log, commit, and refresh."""
    thread.message_count += 1
    thread.last_message_at = datetime.utcnow()

    channel.message_count += 1
    channel.last_message_at = datetime.utcnow()

    await audit_log_write(
        db, user_id, "message.created", "message", message.id,
        channel_id=thread.channel_id, thread_id=message.thread_id,
        details={"message_type": message_type},
    )
    await db.commit()
    await db.refresh(message)
