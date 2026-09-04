"""
Channel-attachment statistics:

  GET    /stats/{channel_id}
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.attachment import Attachment
from app.models.channel import Channel
from app.schemas.attachment import AttachmentStats

router = APIRouter()


@router.get("/stats/{channel_id}", response_model=AttachmentStats)
async def get_attachment_stats(
    channel_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> AttachmentStats:
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
