"""
Private post-creation helpers for create.py (POST /): optional
message/attachment creation, checklist creation, and response building.
Extracted so create.py's own handler body stays under the
150-line-per-file target; not reused by any other endpoint.
"""

import uuid
from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from ._shared import format_due_date_for_response


async def attach_optional_message(db: AsyncSession, task, task_data, message, workspace_id, channel, channel_id, thread_id, user) -> None:
    """If message_content/attachment_ids were provided at creation time,
    create the linked message (and attach any attachments), then point the
    task at it."""
    if not (task_data.message_content or task_data.attachment_ids):
        return

    from app.core.auth import generate_message_id
    from app.models.attachment import Attachment
    from app.models.message import Message

    new_message = Message(
        id=generate_message_id(),
        content=task_data.message_content or f"Task created: {task_data.title}",
        message_type="user",
        thread_id=thread_id,
        channel_id=channel_id,
        workspace_id=workspace_id,
        user_id=user.id,
        sequence_number=message.sequence_number + 1  # Add after the original message
    )

    db.add(new_message)

    # Update channel metadata
    channel.message_count += 1
    channel.last_message_at = datetime.utcnow()

    await db.commit()
    await db.refresh(new_message)

    # Link attachments to the new message if provided
    if task_data.attachment_ids:
        for attachment_id in task_data.attachment_ids:
            try:
                attachment_uuid = uuid.UUID(attachment_id)
                attachment_stmt = select(Attachment).where(
                    and_(
                        Attachment.id == attachment_uuid,
                        Attachment.channel_id == channel_id,
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

    # Update task to reference the new message
    task.message_id = new_message.id
    await db.commit()


async def create_task_checklists(db: AsyncSession, task, task_data) -> None:
    """Create checklist rows attached to the newly-created task, if provided."""
    if not task_data.checklists:
        return

    from app.models.checklist import Checklist

    for i, checklist_item in enumerate(task_data.checklists):
        checklist = Checklist(
            id=uuid.uuid4(),
            task_id=task.id,
            text=checklist_item.get('text', f'Checklist Item {i+1}'),
            order_index=checklist_item.get('order_index', i),
            checklist_metadata=checklist_item.get('checklist_metadata')
        )
        db.add(checklist)

    await db.commit()


def build_create_response(task) -> dict:
    """Build the hand-rolled response dict returned by create_task."""
    return {
        'id': str(task.id),
        'title': task.title,
        'description': task.description,
        'status': task.status,
        'source': task.source,
        'due_date': format_due_date_for_response(task.due_date),
        'priority': task.priority,
        'tags': task.tags,
        'task_metadata': task.task_metadata,
        'assigned_to': str(task.assigned_to) if task.assigned_to else None,
        'created_by': str(task.created_by) if task.created_by else None,
        'message_id': str(task.message_id) if task.message_id else None,
        'created_at': task.created_at,
        'updated_at': task.updated_at,
        'completed_at': getattr(task, 'completed_at', None),
        'checklists': []
    }
