"""
Single task-attachment by ID: delete / update.

  DELETE /task/{task_id}/attachments/{attachment_id}
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
from app.services.file_storage import get_file_storage_service
from .helpers import _task_attachment_fields

router = APIRouter()


@router.delete("/task/{task_id}/attachments/{attachment_id}")
async def delete_task_attachment(
    task_id: str,
    attachment_id: str,
    request: Request = None,
    db: AsyncSession = Depends(get_db)
) -> dict:
    """Delete a specific attachment from a task"""
    user = await get_current_user_required(request)

    # Get task
    from app.models.task import Task
    task_stmt = select(Task).where(Task.id == task_id)
    result = await db.execute(task_stmt)
    task = result.scalar_one_or_none()

    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found"
        )

    # Check if user has access to the task
    if task.workspace_id:
        from app.models.workspace import Workspace
        workspace_stmt = select(Workspace).where(Workspace.id == task.workspace_id)
        workspace_result = await db.execute(workspace_stmt)
        workspace = workspace_result.scalar_one_or_none()

        if workspace and not workspace.is_accessible_by_user(user.company_id, user.role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to task workspace"
            )

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

    # Check if user can delete the attachment
    if str(attachment.user_id) != str(user.id) and user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the attachment owner or admin can delete attachments"
        )

    # Delete file from storage
    try:
        storage_service = get_file_storage_service()
        await storage_service.delete_file(attachment.file_path)
    except Exception as e:
        print(f"Failed to delete file {attachment.file_path}: {e}")

    # Delete from database
    await db.delete(attachment)
    await db.commit()

    return {"message": "Task attachment deleted successfully"}


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

    # Get task
    from app.models.task import Task
    task_stmt = select(Task).where(Task.id == task_id)
    result = await db.execute(task_stmt)
    task = result.scalar_one_or_none()

    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found"
        )

    # Check if user has access to the task
    if task.workspace_id:
        from app.models.workspace import Workspace
        workspace_stmt = select(Workspace).where(Workspace.id == task.workspace_id)
        workspace_result = await db.execute(workspace_stmt)
        workspace = workspace_result.scalar_one_or_none()

        if workspace and not workspace.is_accessible_by_user(user.company_id, user.role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to task workspace"
            )

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
