"""
store_ml_messages sub-step: bump thread/channel counters, audit-log both
messages, commit, and refresh.

Split out of app/routes/messages/ml_store.py — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, wave B2.

NOTE: tests/test_messages_characterization.py patches
`app.routes.messages.ml_store_persist.audit_log_write` — keep this import
name stable if this file moves again.
"""

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.channel import Channel
from app.models.message import Message, Thread
from app.services.audit_service import log as audit_log_write


async def persist_ml_messages(
    db: AsyncSession,
    thread: Thread,
    channel: Channel,
    user_message: Message,
    system_message: Message,
    actor_user_id,
) -> None:
    """Update thread/channel metadata, audit-log both messages, commit, and refresh."""
    thread.message_count += 2  # We're adding 2 messages
    thread.last_message_at = datetime.utcnow()

    channel.message_count += 2  # We're adding 2 messages
    channel.last_message_at = datetime.utcnow()

    await audit_log_write(
        db, actor_user_id, "message.created", "message", user_message.id,
        channel_id=thread.channel_id, thread_id=thread.id,
        details={"source": "ml-store", "message_type": "user"},
    )
    await audit_log_write(
        db, actor_user_id, "message.created", "message", system_message.id,
        channel_id=thread.channel_id, thread_id=thread.id,
        details={"source": "ml-store", "message_type": "system"},
    )
    await db.commit()

    await db.refresh(user_message)
    await db.refresh(system_message)
