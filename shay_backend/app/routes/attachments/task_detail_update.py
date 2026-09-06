"""
Single task-attachment update:

  PUT    /task/{task_id}/attachments/{attachment_id}
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.attachment import Attachment
from app.schemas.attachment import AttachmentUpdate, TaskAttachmentResponse
from .helpers import _task_attachment_fields
from .task_access import _check_task_access, _get_task_or_404

router = APIRouter()


@router.put("/task/{task_id}/attachments/{attachment_id}", response_model=TaskAttachmentResponse)
async def update_task_attachment(
    task_id: str,
    attachment_id: str,
    attachment_update: AttachmentUpdate,
    request: Request = None,
    db: AsyncSession = Depends(get_db)
) -> TaskAttachmentResponse:
    """Update a specific attachment for a task"""
    user = await get_current_user_required(request)

    task = await _get_task_or_404(db, task_id)
    await _check_task_access(db, task, user)

    # Get attachment
    attachment_stmt = select(Attachment).where(
        Attachment.id == attachment_id,
        Attachment.task_id == task_id
    )
    result = await db.execute(attachment_stmt)
    attachment = result.scalar_one_or_none()

    if not attachment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attachment not found"
        )

    # Check if user can update the attachment
    if str(attachment.user_id) != str(user.id) and user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the attachment owner or admin can update attachments"
        )

    # Update attachment fields
    update_data = attachment_update.dict(exclude_unset=True)

    # Only allow updating certain fields for security
    allowed_update_fields = {
        'is_public', 'content_summary', 'processing_status',
        'processing_error', 'is_processed', 'log_entries_count',
        'error_count', 'warning_count'
    }

    filtered_update_data = {k: v for k, v in update_data.items() if k in allowed_update_fields}

    # Update the attachment
    for field, value in filtered_update_data.items():
        setattr(attachment, field, value)

    # Set updated timestamp
    attachment.updated_at = datetime.utcnow()

    await db.commit()
    await db.refresh(attachment)

    # Convert to response model
    return TaskAttachmentResponse(**_task_attachment_fields(attachment))
