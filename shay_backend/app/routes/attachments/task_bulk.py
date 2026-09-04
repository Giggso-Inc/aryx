"""
Task-attachment bulk upload:

  POST   /task/{task_id}/bulk-upload

Stated exception (bug preserved as-is, same root cause as task_upload.py):
`file_path=storage_info.get("file_path", destination_path)` references
`destination_path`, which this function never assigns (only
`structured_path` is defined) — every per-file iteration raises NameError,
which the handler's own bottom `except Exception` catches and reports as a
500. Characterized by
tests/test_attachments_characterization.py::TestBulkUploadTaskAttachments,
not fixed here.
"""

import os
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import generate_attachment_id
from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.attachment import Attachment
from app.models.company import Company
from app.schemas.attachment import TaskAttachmentResponse
from app.services.file_storage import generate_structured_path, get_file_storage_service
from .helpers import _task_attachment_fields

router = APIRouter()


@router.post("/task/{task_id}/bulk-upload", response_model=List[TaskAttachmentResponse])
async def bulk_upload_task_attachments(
    task_id: str,
    files: List[UploadFile] = File(...),
    is_public: bool = Query(False),
    request: Request = None,
    db: AsyncSession = Depends(get_db)
) -> List[TaskAttachmentResponse]:
    """Upload multiple file attachments to a specific task"""
    user = await get_current_user_required(request)

    # Validate number of files (limit to 20 files per bulk upload for tasks)
    if len(files) > 20:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Maximum 20 files allowed per bulk upload for tasks"
        )

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

    # Get company information for structured path
    company_stmt = select(Company).where(Company.id == user.company_id)
    company_result = await db.execute(company_stmt)
    company = company_result.scalar_one_or_none()

    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company not found"
        )

    # Validate total file size (limit to 200MB total for tasks)
    total_size = 0
    for file in files:
        if file.size:
            total_size += file.size

    max_total_size = 200 * 1024 * 1024  # 200MB
    if total_size > max_total_size:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Total file size exceeds maximum allowed size of 200MB"
        )

    # Validate file types - allow common file types for tasks
    allowed_extensions = ['.jpeg', '.jpg', '.png', '.pdf', '.txt', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.zip', '.rar', '.mp4', '.avi', '.mp3', '.wav', '.csv', '.json', '.xml', '.log']

    attachments = []
    storage_service = get_file_storage_service()

    try:
        for file in files:
            # Validate file type
            file_extension = os.path.splitext(file.filename)[1].lower()
            if file_extension not in allowed_extensions:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"File type {file_extension} not allowed for {file.filename}. Allowed types: {', '.join(allowed_extensions)}"
                )

            # Validate individual file size (50MB limit for task attachments)
            max_file_size = 50 * 1024 * 1024  # 50MB
            if file.size and file.size > max_file_size:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"File {file.filename} size exceeds maximum allowed size of 50MB"
                )

            # Read file content
            content = await file.read()

            # Generate structured path for task attachment files
            attachment_id = generate_attachment_id()
            filename = f"{attachment_id}{file_extension}"
            base_filename = os.path.splitext(file.filename)[0]
            current_date = datetime.now().strftime("%Y-%m-%d")

            # Use structured path for task attachment files
            structured_path = generate_structured_path(
                company_name=company.name,
                company_id=str(company.id),
                file_type="task_attachment",
                original_filename=file.filename,
                base_filename=base_filename,
                file_extension=file_extension,
                current_date=current_date
            )

            # Upload file using storage service
            try:
                storage_info = await storage_service.upload_file(
                    file_content=content,
                    destination_path=structured_path,
                    original_filename=file.filename
                )
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to upload file {file.filename}: {str(e)}"
                )

            # Create attachment record
            attachment = Attachment(
                id=attachment_id,
                filename=filename,
                original_filename=file.filename,
                file_path=storage_info.get("file_path", destination_path),
                file_size=len(content),
                mime_type=file.content_type or "application/octet-stream",
                file_extension=file_extension,
                task_id=task_id,
                channel_id=task.channel_id,
                workspace_id=task.workspace_id,
                user_id=user.id,
                is_public=is_public,
                storage_provider=storage_info.get("storage_provider", "local"),
                storage_url=storage_info.get("storage_url")
            )

            attachments.append(attachment)

        # Add all attachments to database
        db.add_all(attachments)
        await db.commit()

        # Refresh all attachments
        for attachment in attachments:
            await db.refresh(attachment)

        # Convert to response models
        task_attachments = [
            TaskAttachmentResponse(**_task_attachment_fields(attachment))
            for attachment in attachments
        ]

        return task_attachments

    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        # If any other error occurs, try to clean up uploaded files
        for attachment in attachments:
            try:
                if hasattr(attachment, 'file_path') and attachment.file_path:
                    await storage_service.delete_file(attachment.file_path)
            except:
                pass  # Ignore cleanup errors

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Bulk task upload failed: {str(e)}"
        )
