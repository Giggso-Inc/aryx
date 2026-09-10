"""
Per-file validation and processing helpers for the task-attachment
bulk-upload endpoint (task_bulk.py). Split out purely to keep the endpoint
itself under the 150-line limit; no behavior change.

Stated exception carried over from task_bulk.py's original docstring: the
attachment construction below references `destination_path`, which is never
assigned (only `structured_path` is) — every call raises NameError, caught
by the endpoint's own top-level `except Exception` and reported as a 500.
Characterized by
tests/test_attachments_characterization.py::TestBulkUploadTaskAttachments,
not fixed here.
"""

import os
from datetime import datetime

from fastapi import HTTPException, status

from app.core.auth import generate_attachment_id
from app.models.attachment import Attachment
from app.services.file_storage import generate_structured_path

ALLOWED_EXTENSIONS = ['.jpeg', '.jpg', '.png', '.pdf', '.txt', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.zip', '.rar', '.mp4', '.avi', '.mp3', '.wav', '.csv', '.json', '.xml', '.log']

_MAX_FILES = 20
_MAX_TOTAL_SIZE = 200 * 1024 * 1024  # 200MB
_MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB


def _validate_file_count(files) -> None:
    if len(files) > _MAX_FILES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Maximum 20 files allowed per bulk upload for tasks"
        )


def _validate_total_size(files) -> None:
    total_size = 0
    for file in files:
        if file.size:
            total_size += file.size

    if total_size > _MAX_TOTAL_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Total file size exceeds maximum allowed size of 200MB"
        )


async def _process_one_file(file, task_id, task, company, user, is_public, storage_service) -> Attachment:
    # Validate file type
    file_extension = os.path.splitext(file.filename)[1].lower()
    if file_extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File type {file_extension} not allowed for {file.filename}. Allowed types: {', '.join(ALLOWED_EXTENSIONS)}"
        )

    # Validate individual file size (50MB limit for task attachments)
    if file.size and file.size > _MAX_FILE_SIZE:
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
    return Attachment(
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
