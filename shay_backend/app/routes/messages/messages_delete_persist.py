"""
delete_message sub-step: audit-log and delete the main message row.

Split out of app/routes/messages/messages_delete.py — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, wave B2.

NOTE: tests/test_messages_characterization.py patches
`app.routes.messages.messages_delete_persist.audit_log_write` — keep this
import name stable if this file moves again.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.message import Message
from app.services.audit_service import log as audit_log_write


async def audit_and_delete_message(db: AsyncSession, message: Message, user_id) -> None:
    """Audit-log the deletion, then mark the main message row for deletion."""
    await audit_log_write(
        db, user_id, "message.deleted", "message", message.id,
        channel_id=message.channel_id, thread_id=message.thread_id,
    )
    await db.delete(message)
