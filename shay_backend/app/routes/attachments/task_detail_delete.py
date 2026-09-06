"""
Single task-attachment delete:

  DELETE /task/{task_id}/attachments/{attachment_id}
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.attachment import Attachment
from app.services.file_storage import get_file_storage_service
from .task_access import _check_task_access, _get_task_or_404

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
