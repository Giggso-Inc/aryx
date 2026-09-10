"""
Task-attachment statistics:

  GET    /task/{task_id}/attachments/stats
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.attachment import Attachment
from app.schemas.attachment import TaskAttachmentStats

router = APIRouter()


@router.get("/task/{task_id}/attachments/stats", response_model=TaskAttachmentStats)
async def get_task_attachment_stats(
    task_id: str,
    request: Request = None,
    db: AsyncSession = Depends(get_db)
) -> TaskAttachmentStats:
    """Get attachment statistics for a specific task"""
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

    # Get basic statistics
    total_query = select(func.count(Attachment.id)).where(Attachment.task_id == task_id)
    total_result = await db.execute(total_query)
    total_attachments = total_result.scalar()

    size_query = select(func.sum(Attachment.file_size)).where(Attachment.task_id == task_id)
    size_result = await db.execute(size_query)
    total_size_bytes = size_result.scalar() or 0

    processed_query = select(func.count(Attachment.id)).where(
        Attachment.task_id == task_id,
        Attachment.processing_status == "completed"
    )
    processed_result = await db.execute(processed_query)
    processed_count = processed_result.scalar()

    failed_query = select(func.count(Attachment.id)).where(
        Attachment.task_id == task_id,
        Attachment.processing_status == "failed"
    )
    failed_result = await db.execute(failed_query)
    failed_count = failed_result.scalar()

    pending_query = select(func.count(Attachment.id)).where(
        Attachment.task_id == task_id,
        Attachment.processing_status == "pending"
    )
    pending_result = await db.execute(pending_query)
    pending_count = pending_result.scalar()

    # Count by file type
    file_type_query = select(
        Attachment.file_extension,
        func.count(Attachment.id)
    ).where(Attachment.task_id == task_id).group_by(Attachment.file_extension)

    file_type_result = await db.execute(file_type_query)
    by_file_type = {row[0]: row[1] for row in file_type_result}

    return TaskAttachmentStats(
        total_attachments=total_attachments,
        total_size_bytes=total_size_bytes,
        processed_count=processed_count,
        failed_count=failed_count,
        pending_count=pending_count,
        by_file_type=by_file_type
    )
