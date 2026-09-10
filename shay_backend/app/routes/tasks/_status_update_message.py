"""
Private helper for status_update.py's POST /{task_id}/status endpoint:
handles the optional message-content + attachment-linking side effect of a
status update. Not reused by any other endpoint — split out purely to keep
status_update.py itself under the 150-line style target. No routes here.
"""

import uuid
from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.models.task import Task
from app.models.channel import Channel
from app.models.message import Message
from app.models.user import User
from app.schemas.task import TaskStatusUpdateRequest


async def create_status_message_and_link_attachments(
    task: Task,
    status_data: TaskStatusUpdateRequest,
    status_channel_id: object,
    status_thread_id: object,
    status_workspace_id: object,
    user: User,
    db: AsyncSession,
) -> None:
    """Create an optional message documenting the status change and link any
    provided attachment IDs to it, mirroring the original inline behavior."""
    from app.core.auth import generate_message_id
    from app.models.attachment import Attachment

    if not status_thread_id:
        return

    new_message = Message(
        id=generate_message_id(),
        content=status_data.message_content or f"Task status updated to {status_data.status}",
        message_type="user",
        thread_id=status_thread_id,
        channel_id=status_channel_id,
        workspace_id=status_workspace_id,
        user_id=user.id,
        sequence_number=1  # Will be updated by the message system
    )

    db.add(new_message)

    if status_channel_id:
        channel_stmt = select(Channel).where(Channel.id == status_channel_id)
        channel_result = await db.execute(channel_stmt)
        channel = channel_result.scalar_one_or_none()
        if channel:
            channel.message_count += 1
            channel.last_message_at = datetime.utcnow()

    await db.commit()
    await db.refresh(new_message)

    if not status_data.attachment_ids:
        return

    for attachment_id in status_data.attachment_ids:
        try:
            attachment_uuid = uuid.UUID(attachment_id)
            attachment_stmt = select(Attachment).where(
                and_(
                    Attachment.id == attachment_uuid,
                    Attachment.channel_id == status_channel_id,
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
