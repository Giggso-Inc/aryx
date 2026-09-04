"""
Channel-attachment listing:

  GET    /
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.attachment import Attachment
from app.models.channel import Channel
from app.schemas.attachment import AttachmentList, AttachmentResponse

router = APIRouter()


@router.get("/", response_model=AttachmentList)
async def list_attachments(
    channel_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    search: Optional[str] = Query(None)
) -> AttachmentList:
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
