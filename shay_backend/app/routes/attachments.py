"""
Attachment routes for file upload and management
"""

import os
import aiofiles
from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, HTTPException, status, Request, Depends, Query, UploadFile, File
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.database import get_db
from app.core.auth import generate_attachment_id
from app.core.config import settings
from app.middleware.auth_middleware import get_current_user_required
from app.models.user import User
from app.models.workspace import Workspace
from app.models.channel import Channel
from app.models.attachment import Attachment
from app.models.company import Company
from app.services.audit_service import log as audit_log_write
from app.services.file_storage import get_file_storage_service, generate_structured_path
from app.schemas.attachment import (
    AttachmentCreate,
    AttachmentUpdate,
    AttachmentResponse,
    AttachmentList,
    AttachmentStats,
    TaskAttachmentCreate,
    TaskAttachmentResponse,
    TaskAttachmentList,
    TaskAttachmentStats
)

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
):
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


@router.get("/", response_model=AttachmentList)
async def list_attachments(
    channel_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    search: Optional[str] = Query(None)
):
    """List attachments in a channel"""
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
    
    # Build query
    query = select(Attachment).where(Attachment.channel_id == channel_id)
    
    # Add search filter
    if search:
        query = query.where(Attachment.original_filename.ilike(f"%{search}%"))
    
    # Add pagination
    offset = (page - 1) * size
    query = query.offset(offset).limit(size).order_by(Attachment.created_at.desc())
    
    # Execute query
    result = await db.execute(query)
    attachments = result.scalars().all()
    
    # Get total count
    count_query = select(func.count(Attachment.id)).where(Attachment.channel_id == channel_id)
    if search:
        count_query = count_query.where(Attachment.original_filename.ilike(f"%{search}%"))
    
    count_result = await db.execute(count_query)
    total = count_result.scalar()
    
    return AttachmentList(
        attachments=[AttachmentResponse.from_orm(a) for a in attachments],
        total=total,
        page=page,
        size=size
    )


@router.get("/{attachment_id}", response_model=AttachmentResponse)
async def get_attachment(
    attachment_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Get attachment by ID"""
    user = await get_current_user_required(request)
    
    # Get attachment
    stmt = select(Attachment).where(Attachment.id == attachment_id)
    result = await db.execute(stmt)
    attachment = result.scalar_one_or_none()
    
    if not attachment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attachment not found"
        )
    
    # Check permissions
    if not attachment.can_be_accessed_by_user(user.id, user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to attachment"
        )
    
    return AttachmentResponse.from_orm(attachment)


@router.get("/{attachment_id}/download")
async def download_attachment(
    attachment_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Download attachment file"""
    user = await get_current_user_required(request)
    
    # Get attachment
    stmt = select(Attachment).where(Attachment.id == attachment_id)
    result = await db.execute(stmt)
    attachment = result.scalar_one_or_none()
    
    if not attachment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attachment not found"
        )
    
    # Check permissions
    if not attachment.can_be_accessed_by_user(user.id, user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to attachment"
        )
    
    # Download file using storage service
    try:
        storage_service = get_file_storage_service()
        file_content = await storage_service.download_file(attachment.file_path)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File not found or failed to download: {str(e)}"
        )
    
    # Return file content as response
    from fastapi.responses import Response
    return Response(
        content=file_content,
        media_type=attachment.mime_type,
        headers={
            "Content-Disposition": f"attachment; filename={attachment.original_filename}"
        }
    )


@router.delete("/{attachment_id}")
async def delete_attachment(
    attachment_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Delete attachment"""
    user = await get_current_user_required(request)
    
    # Get attachment
    stmt = select(Attachment).where(Attachment.id == attachment_id)
    result = await db.execute(stmt)
    attachment = result.scalar_one_or_none()
    
    if not attachment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attachment not found"
        )
    
    # Check permissions
    if not attachment.can_be_accessed_by_user(user.id, user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to attachment"
        )
    
    # Delete file from storage
    try:
        storage_service = get_file_storage_service()
        await storage_service.delete_file(attachment.file_path)
    except Exception as e:
        print(f"Failed to delete file {attachment.file_path}: {e}")
    
    await audit_log_write(db, user.id, "attachment.deleted", "attachment", attachment.id, channel_id=attachment.channel_id)
    await db.delete(attachment)
    await db.commit()
    
    return {"message": "Attachment deleted successfully"}


@router.get("/stats/{channel_id}", response_model=AttachmentStats)
async def get_attachment_stats(
    channel_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Get attachment statistics for a channel"""
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
    
    # Get statistics
    total_query = select(func.count(Attachment.id)).where(Attachment.channel_id == channel_id)
    total_result = await db.execute(total_query)
    total_attachments = total_result.scalar()
    
    size_query = select(func.sum(Attachment.file_size)).where(Attachment.channel_id == channel_id)
    size_result = await db.execute(size_query)
    total_size_bytes = size_result.scalar() or 0
    
    processed_query = select(func.count(Attachment.id)).where(
        Attachment.channel_id == channel_id,
        Attachment.processing_status == "completed"
    )
    processed_result = await db.execute(processed_query)
    processed_count = processed_result.scalar()
    
    failed_query = select(func.count(Attachment.id)).where(
        Attachment.channel_id == channel_id,
        Attachment.processing_status == "failed"
    )
    failed_result = await db.execute(failed_query)
    failed_count = failed_result.scalar()
    
    pending_query = select(func.count(Attachment.id)).where(
        Attachment.channel_id == channel_id,
        Attachment.processing_status == "pending"
    )
    pending_result = await db.execute(pending_query)
    pending_count = pending_result.scalar()
    
    # Count by file type
    log_query = select(func.count(Attachment.id)).where(
        Attachment.channel_id == channel_id,
        Attachment.file_extension.in_([".log", ".txt"])
    )
    log_result = await db.execute(log_query)
    log_files_count = log_result.scalar()
    
    json_query = select(func.count(Attachment.id)).where(
        Attachment.channel_id == channel_id,
        Attachment.file_extension == ".json"
    )
    json_result = await db.execute(json_query)
    json_files_count = json_result.scalar()
    
    xml_query = select(func.count(Attachment.id)).where(
        Attachment.channel_id == channel_id,
        Attachment.file_extension == ".xml"
    )
    xml_result = await db.execute(xml_query)
    xml_files_count = xml_result.scalar()
    
    return AttachmentStats(
        total_attachments=total_attachments,
        total_size_bytes=total_size_bytes,
        processed_count=processed_count,
        failed_count=failed_count,
        pending_count=pending_count,
        log_files_count=log_files_count,
        json_files_count=json_files_count,
        xml_files_count=xml_files_count
    )


# Task Attachment Routes
@router.post("/task/{task_id}/upload", response_model=TaskAttachmentResponse)
async def upload_task_attachment(
    task_id: str,
    file: UploadFile = File(...),
    is_public: bool = Query(False),
    request: Request = None,
    db: AsyncSession = Depends(get_db)
):
    """Upload a file attachment to a specific task"""
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
        # Get workspace to check permissions
        from app.models.workspace import Workspace
        workspace_stmt = select(Workspace).where(Workspace.id == task.workspace_id)
        workspace_result = await db.execute(workspace_stmt)
        workspace = workspace_result.scalar_one_or_none()
        
        if workspace and not workspace.is_accessible_by_user(user.company_id, user.role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to task workspace"
            )
    
    # Validate file type - allow common file types
    allowed_extensions = ['.jpeg', '.jpg', '.png', '.pdf', '.txt', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.zip', '.rar', '.mp4', '.avi', '.mp3', '.wav', '.csv', '.json', '.xml', '.log']
    file_extension = os.path.splitext(file.filename)[1].lower()
    
    if file_extension not in allowed_extensions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File type {file_extension} not allowed. Allowed types: {', '.join(allowed_extensions)}"
        )
    
    # Validate file size (50MB limit for task attachments)
    max_file_size = 50 * 1024 * 1024  # 50MB
    if file.size and file.size > max_file_size:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File size exceeds maximum allowed size of 50MB"
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
        id=attachment_id,  # Set the generated ID
        filename=filename,
        original_filename=file.filename,
        file_path=storage_info.get("file_path", destination_path),
        file_size=len(content),
        mime_type=file.content_type or "application/octet-stream",
        file_extension=file_extension,
        task_id=task_id,
        channel_id=task.channel_id,  # Default if no channel
        workspace_id=task.workspace_id,  # Default if no workspace
        user_id=user.id,
        is_public=is_public,
        storage_provider=storage_info.get("storage_provider", "local"),
        storage_url=storage_info.get("storage_url")
    )
    
    db.add(attachment)
    await db.commit()
    await db.refresh(attachment)
    
    return attachment


@router.get("/task/{task_id}/attachments", response_model=TaskAttachmentList)
async def get_task_attachments(
    task_id: str,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    request: Request = None,
    db: AsyncSession = Depends(get_db)
):
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
    from app.schemas.attachment import TaskAttachmentResponse
    task_attachments = []
    for attachment in attachments:
        task_attachment_data = {
            "id": attachment.id,
            "task_id": attachment.task_id,
            "filename": attachment.filename,
            "original_filename": attachment.original_filename,
            "file_size": attachment.file_size,
            "mime_type": attachment.mime_type,
            "file_extension": attachment.file_extension,
            "workspace_id": attachment.workspace_id,
            "user_id": attachment.user_id,
            "is_processed": attachment.is_processed,
            "processing_status": attachment.processing_status,
            "processing_error": attachment.processing_error,
            "is_public": attachment.is_public,
            "content_summary": attachment.content_summary,
            "log_entries_count": attachment.log_entries_count,
            "error_count": attachment.error_count,
            "warning_count": attachment.warning_count,
            "created_at": attachment.created_at,
            "updated_at": attachment.updated_at
        }
        task_attachments.append(TaskAttachmentResponse(**task_attachment_data))
    
    return TaskAttachmentList(
        attachments=task_attachments,
        total=total,
        page=page,
        size=size
    )


@router.get("/task/{task_id}/attachments/stats", response_model=TaskAttachmentStats)
async def get_task_attachment_stats(
    task_id: str,
    request: Request = None,
    db: AsyncSession = Depends(get_db)
):
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


@router.delete("/task/{task_id}/attachments/{attachment_id}")
async def delete_task_attachment(
    task_id: str,
    attachment_id: str,
    request: Request = None,
    db: AsyncSession = Depends(get_db)
):
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
):
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
    from app.schemas.attachment import TaskAttachmentResponse
    task_attachment_data = {
        "id": attachment.id,
        "task_id": attachment.task_id,
        "filename": attachment.filename,
        "original_filename": attachment.original_filename,
        "file_size": attachment.file_size,
        "mime_type": attachment.mime_type,
        "file_extension": attachment.file_extension,
        "workspace_id": attachment.workspace_id,
        "user_id": attachment.user_id,
        "is_processed": attachment.is_processed,
        "processing_status": attachment.processing_status,
        "processing_error": attachment.processing_error,
        "is_public": attachment.is_public,
        "content_summary": attachment.content_summary,
        "log_entries_count": attachment.log_entries_count,
        "error_count": attachment.error_count,
        "warning_count": attachment.warning_count,
        "created_at": attachment.created_at,
        "updated_at": attachment.updated_at
    }
    
    return TaskAttachmentResponse(**task_attachment_data)


@router.post("/task/{task_id}/bulk-upload", response_model=List[TaskAttachmentResponse])
async def bulk_upload_task_attachments(
    task_id: str,
    files: List[UploadFile] = File(...),
    is_public: bool = Query(False),
    request: Request = None,
    db: AsyncSession = Depends(get_db)
):
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
        from app.schemas.attachment import TaskAttachmentResponse
        task_attachments = []
        for attachment in attachments:
            task_attachment_data = {
                "id": attachment.id,
                "task_id": attachment.task_id,
                "filename": attachment.filename,
                "original_filename": attachment.original_filename,
                "file_size": attachment.file_size,
                "mime_type": attachment.mime_type,
                "file_extension": attachment.file_extension,
                "workspace_id": attachment.workspace_id,
                "user_id": attachment.user_id,
                "is_processed": attachment.is_processed,
                "processing_status": attachment.processing_status,
                "processing_error": attachment.processing_error,
                "is_public": attachment.is_public,
                "content_summary": attachment.content_summary,
                "log_entries_count": attachment.log_entries_count,
                "error_count": attachment.error_count,
                "warning_count": attachment.warning_count,
                "created_at": attachment.created_at,
                "updated_at": attachment.updated_at
            }
            task_attachments.append(TaskAttachmentResponse(**task_attachment_data))
        
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