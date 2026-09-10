"""
delete_message sub-step: clean up dependent messages (e.g. AI/system replies
whose query_id points at the message being deleted).

Split out of app/routes/messages/messages_delete.py — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, wave B2.
"""

from typing import List, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.attachment import Attachment
from app.models.ai_response import AIResponse
from app.models.message import Message
from app.services.file_storage import get_file_storage_service


async def cleanup_dependent_messages(db: AsyncSession, message: Message) -> Tuple[List[Message], int, int]:
    """
    Find and delete any messages that reference `message` as their query_id
    (e.g. AI responses stored in gg_messages), unlinking their attachments
    and deleting their AIResponse rows along the way.

    Returns:
        (dependent_messages, deleted_attachments_count, deleted_ai_count)
    """
    dependent_stmt = select(Message).where(Message.query_id == message.id)
    dependent_result = await db.execute(dependent_stmt)
    dependent_messages = dependent_result.scalars().all()

    deleted_attachments_count = 0
    deleted_ai_count = 0

    for dep_msg in dependent_messages:
        # Unlink attachments from dependent message
        if dep_msg.attachment_ids:
            dep_att_stmt = select(Attachment).where(Attachment.message_id == dep_msg.id)
            dep_att_result = await db.execute(dep_att_stmt)
            dep_attachments = dep_att_result.scalars().all()
            for att in dep_attachments:
                try:
                    storage_service = get_file_storage_service()
                    await storage_service.delete_file(att.file_path)
                    deleted_attachments_count += 1
                except Exception:
                    pass
                att.message_id = None

        # Delete AI responses for this dependent message
        dep_ai_stmt = select(AIResponse).where(AIResponse.message_id == dep_msg.id)
        dep_ai_result = await db.execute(dep_ai_stmt)
        dep_ai = dep_ai_result.scalars().all()
        for ai in dep_ai:
            await db.delete(ai)
            deleted_ai_count += 1

        await db.delete(dep_msg)

    return dependent_messages, deleted_attachments_count, deleted_ai_count
