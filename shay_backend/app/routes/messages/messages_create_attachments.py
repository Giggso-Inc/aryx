"""
create_message sub-steps: attachment_ids parsing and linking to the new
message.

Split out of app/routes/messages/messages_create.py — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, wave B2.
"""

from typing import List, Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.attachment import Attachment
from app.models.message import Message


def parse_attachment_uuids(attachment_ids: Optional[List[str]]) -> Optional[List[UUID]]:
    """Convert string attachment ids to UUIDs, or raise 400 on bad input."""
    if not attachment_ids:
        return None

    try:
        return [UUID(attachment_id) for attachment_id in attachment_ids]
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid attachment ID format: {str(e)}"
        )


async def link_attachments_to_message(
    db: AsyncSession,
    message: Message,
    attachment_ids: Optional[List[str]],
    channel_id,
    user_id,
) -> None:
    """
    Validate each attachment belongs to the posting user in this channel and
    link it to the newly created message.
    """
    if not attachment_ids:
        return

    for attachment_id in attachment_ids:
        try:
            attachment_uuid = UUID(attachment_id)
            attachment_stmt = select(Attachment).where(
                and_(
                    Attachment.id == attachment_uuid,
                    Attachment.channel_id == channel_id,
                    Attachment.user_id == user_id  # Ensure user owns the attachment
                )
            )
            attachment_result = await db.execute(attachment_stmt)
            attachment = attachment_result.scalar_one_or_none()

            if attachment:
                # Link attachment to message
                attachment.message_id = message.id
            else:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Attachment {attachment_id} not found or access denied"
                )
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid attachment ID format: {attachment_id}"
            )
