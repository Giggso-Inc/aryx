"""
Channel-attachment upload:

  POST   /upload
"""

import os
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import generate_attachment_id
from app.core.config import settings
from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.attachment import Attachment
from app.models.channel import Channel
from app.models.company import Company
from app.schemas.attachment import AttachmentResponse
from app.services.audit_service import log as audit_log_write
from app.services.file_storage import generate_structured_path, get_file_storage_service

router = APIRouter()


@router.post("/upload", response_model=AttachmentResponse)
async def upload_file(
    file: UploadFile = File(...),
    channel_id: str = Query(...),
    message_id: Optional[str] = Query(None),
    task_id: Optional[str] = Query(None),
    is_public: bool = Query(False),
    request: Request = None,
    db: AsyncSession = Depends(get_db)
) -> AttachmentResponse:
    """Upload a file attachment"""
    user = await get_current_user_required(request)

    # Get channel
    stmt = select(Channel).where(Channel.id == channel_id)
    result = await db.execute(stmt)
    channel = result.scalar_one_or_none()

    if not channel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Channel not found"
        )

    # Check permissions
    if not channel.is_accessible_by_user(user.company_id, user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to channel"
        )

    # Validate file type
    file_extension = os.path.splitext(file.filename)[1].lower()
    if file_extension not in settings.ALLOWED_FILE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File type {file_extension} not allowed. Allowed types: {settings.ALLOWED_FILE_TYPES}"
        )

    # Validate file size
    if file.size and file.size > settings.MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File size exceeds maximum allowed size of {settings.MAX_FILE_SIZE / (1024*1024)}MB"
        )

    # Read file content
    content = await file.read()

    # Get company information for structured path
    company_stmt = select(Company).where(Company.id == user.company_id)
    company_result = await db.execute(company_stmt)
    company = company_result.scalar_one_or_none()

    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company not found"
        )

    # Generate structured path for attachment files
    attachment_id = generate_attachment_id()
    filename = f"{attachment_id}{file_extension}"
    base_filename = os.path.splitext(file.filename)[0]
    current_date = datetime.now().strftime("%Y-%m-%d")

    # Use structured path for attachment files
    structured_path = generate_structured_path(
        company_name=company.name,
        company_id=str(company.id),
        file_type="attachment",
        original_filename=file.filename,
        base_filename=base_filename,
        file_extension=file_extension,
        current_date=current_date
    )

    # Upload file using storage service
    try:
        storage_service = get_file_storage_service()
        storage_info = await storage_service.upload_file(
            file_content=content,
            destination_path=structured_path,
            original_filename=file.filename
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload file: {str(e)}"
        )

    # Create attachment record
    attachment = Attachment(
        id=attachment_id,
        filename=filename,
        original_filename=file.filename,
        file_path=storage_info["storage_path"],
        file_size=len(content),
        mime_type=file.content_type or "application/octet-stream",
        file_extension=file_extension,
        storage_provider=storage_info["provider"],
        storage_url=storage_info["file_url"],
        message_id=message_id,
        task_id=task_id,
        channel_id=channel_id,
        workspace_id=channel.workspace_id,  # Use channel's workspace_id for backward compatibility
        user_id=user.id,
        is_public=is_public
    )

    db.add(attachment)
    await audit_log_write(db, user.id, "attachment.uploaded", "attachment", attachment.id, channel_id=channel.id)
    await db.commit()
    await db.refresh(attachment)

    return AttachmentResponse.from_orm(attachment)
