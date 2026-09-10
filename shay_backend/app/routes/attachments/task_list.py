"""
Task-attachment listing:

  GET    /task/{task_id}/attachments
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.attachment import Attachment
from app.schemas.attachment import TaskAttachmentList, TaskAttachmentResponse
from .helpers import _task_attachment_fields

router = APIRouter()


@router.get("/task/{task_id}/attachments", response_model=TaskAttachmentList)
async def get_task_attachments(
    task_id: str,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    request: Request = None,
    db: AsyncSession = Depends(get_db)
) -> TaskAttachmentList:
    """Get all attachments for a specific task"""
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

    # Calculate offset
    offset = (page - 1) * size

    # Get attachments for the task
    attachments_stmt = select(Attachment).where(
        Attachment.task_id == task_id
    ).order_by(Attachment.created_at.desc()).offset(offset).limit(size)

    result = await db.execute(attachments_stmt)
    attachments = result.scalars().all()

    # Get total count
    count_stmt = select(func.count(Attachment.id)).where(Attachment.task_id == task_id)
    count_result = await db.execute(count_stmt)
    total = count_result.scalar()

    # Convert Attachment model objects to TaskAttachmentResponse objects
    task_attachments = [
        TaskAttachmentResponse(**_task_attachment_fields(attachment))
        for attachment in attachments
    ]

    return TaskAttachmentList(
        attachments=task_attachments,
        total=total,
        page=page,
        size=size
    )
