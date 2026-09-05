"""
Private helper for update.py (PUT /{task_id}): optional message/attachment
creation on update. Extracted so update.py's own handler body stays under
the 150-line-per-file target; not reused by any other endpoint.
"""

import uuid
from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_


async def attach_optional_update_message(
    db: AsyncSession, task, task_data, user,
    task_channel_id, task_thread_id, task_workspace_id,
) -> None:
    """If message_content/attachment_ids were provided on update, create the
    linked message (and attach any attachments) exactly as before."""
    if not (task_data.message_content or task_data.attachment_ids):
        return
    if not task_thread_id:
        return

    from app.core.auth import generate_message_id
    from app.models.attachment import Attachment
    from app.models.channel import Channel
    from app.models.message import Message

    new_message = Message(
        id=generate_message_id(),
        content=task_data.message_content or f"Task updated: {task.title}",
        message_type="user",
        thread_id=task_thread_id,
        channel_id=task_channel_id,
        workspace_id=task_workspace_id,
        user_id=user.id,
        sequence_number=1  # Will be updated by the message system
    )

    db.add(new_message)

    # Update channel metadata
    if task_channel_id:
        channel_stmt = select(Channel).where(Channel.id == task_channel_id)
        channel_result = await db.execute(channel_stmt)
        channel = channel_result.scalar_one_or_none()
        if channel:
            channel.message_count += 1
            channel.last_message_at = datetime.utcnow()

    await db.commit()
    await db.refresh(new_message)

    if task_data.attachment_ids:
        for attachment_id in task_data.attachment_ids:
            try:
                attachment_uuid = uuid.UUID(attachment_id)
                attachment_stmt = select(Attachment).where(
                    and_(
                        Attachment.id == attachment_uuid,
                        Attachment.channel_id == task_channel_id,
                        Attachment.user_id == user.id  # Ensure user owns the attachment
                    )
                )
                attachment_result = await db.execute(attachment_stmt)
                attachment = attachment_result.scalar_one_or_none()

                if attachment:
                    attachment.message_id = new_message.id
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

        await db.commit()
