"""
Single channel-attachment by ID: get / download / delete.

  GET    /{attachment_id}
  GET    /{attachment_id}/download
  DELETE /{attachment_id}
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.attachment import Attachment
from app.schemas.attachment import AttachmentResponse
from app.services.audit_service import log as audit_log_write
from app.services.file_storage import get_file_storage_service

router = APIRouter()


@router.get("/{attachment_id}", response_model=AttachmentResponse)
async def get_attachment(
    attachment_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> AttachmentResponse:
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
) -> Response:
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
) -> dict:
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
