"""
update_message sub-step: reconcile a message's attachment_ids against the
new list from the request (link newly-added, unlink removed).

Split out of app/routes/messages/messages_update.py — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, wave B2.
"""

from typing import List, Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.attachment import Attachment
from app.models.message import Message


async def reconcile_message_attachments(
    db: AsyncSession,
    message: Message,
    channel_id,
    user_id,
    new_attachment_ids: Optional[List[str]],
) -> None:
    """
    Update message.attachment_ids to match new_attachment_ids: link any newly
    referenced attachments and unlink any previously linked ones that are no
    longer present. If new_attachment_ids is None, existing attachments are
    left untouched.
    """
    if new_attachment_ids is None:
        return

    current_attachment_ids = set(message.attachment_ids) if message.attachment_ids else set()

    new_attachment_uuids = []
    for attachment_id in new_attachment_ids:
        try:
            new_attachment_uuids.append(UUID(attachment_id))
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid attachment ID format: {attachment_id}"
            )

    new_attachment_ids_set = set(new_attachment_uuids)
    for attachment_uuid in new_attachment_uuids:
        attachment_stmt = select(Attachment).where(
            and_(
                Attachment.id == attachment_uuid,
                Attachment.channel_id == channel_id,
                Attachment.user_id == user_id  # Ensure user owns the attachment
            )
        )
        attachment_result = await db.execute(attachment_stmt)
        attachment = attachment_result.scalar_one_or_none()

        if not attachment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Attachment {attachment_uuid} not found or access denied"
            )

        # Link attachment to message
        attachment.message_id = message.id

    # Unlink attachments that are no longer in the list
    attachments_to_unlink = current_attachment_ids - new_attachment_ids_set
    if attachments_to_unlink:
        unlink_stmt = select(Attachment).where(
            and_(
                Attachment.id.in_(attachments_to_unlink),
                Attachment.message_id == message.id
            )
        )
        unlink_result = await db.execute(unlink_stmt)
        attachments_to_remove = unlink_result.scalars().all()
        for attachment in attachments_to_remove:
            attachment.message_id = None

    # Update message.attachment_ids array
    # Empty list means remove all attachments, use None for empty array in database
    message.attachment_ids = new_attachment_uuids if new_attachment_uuids else None
