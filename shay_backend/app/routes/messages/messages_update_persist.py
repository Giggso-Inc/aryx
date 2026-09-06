"""
update_message sub-step: audit-log, commit, and refresh the updated message.

Split out of app/routes/messages/messages_update.py — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, wave B2.

NOTE: tests/test_messages_characterization.py patches
`app.routes.messages.messages_update_persist.audit_log_write` — keep this
import name stable if this file moves again.
"""

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.message import Message
from app.services.audit_service import log as audit_log_write


async def persist_updated_message(db: AsyncSession, message: Message, user_id) -> None:
    """Stamp updated_at, audit-log, commit, and refresh the message."""
    message.updated_at = datetime.utcnow()
    await audit_log_write(
        db, user_id, "message.updated", "message", message.id,
        channel_id=message.channel_id, thread_id=message.thread_id,
    )
    await db.commit()
    await db.refresh(message)
