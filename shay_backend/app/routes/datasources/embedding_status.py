"""
Datasource GET /embedding-status/{channel_id} endpoint.
"""

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import String, and_, desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.expression import literal

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.channel import Channel
from app.models.datasource import Datasource
from app.schemas.datasource import EmbeddingStatusResponse
from app.utils.channel_access import check_channel_access, check_channel_access_by_thread

router = APIRouter()


@router.get("/embedding-status/{channel_id}", response_model=EmbeddingStatusResponse)
async def get_embedding_status_by_channel(
    channel_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    thread_id: Optional[str] = Query(
        None,
        description="Filter by thread ID. When set, returns embedding status only for thread-level datasources (e.g. email attachments in that thread). When omitted, returns channel-level datasources only."
    )
) -> EmbeddingStatusResponse:
    """Get embedding status for datasources in a channel. Pass thread_id to get status for thread-level datasources (email attachments) only."""
    user = await get_current_user_required(request)

    # Check channel access - user must be super admin or channel member
    await check_channel_access(db, user, channel_id)

    # Get channel
    stmt = select(Channel).where(Channel.id == channel_id)
    result = await db.execute(stmt)
    channel = result.scalar_one_or_none()

    if not channel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Channel not found"
        )

    # When thread_id is passed: return only thread-level datasources for that thread (e.g. email attachments)
    # Same behaviour as GET /datasources/?channel_id=...&thread_id=...
    if thread_id:
        try:
            thread_uuid = uuid.UUID(thread_id)
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid thread_id format: {thread_id}"
            )
        await check_channel_access_by_thread(db, user, thread_id)
        # For thread-level datasources: get all datasources for the thread, then filter to keep only latest per filename
        stmt = select(Datasource).where(
            and_(
                Datasource.channel_id == channel_id,
                Datasource.datasource_metadata.isnot(None),
                Datasource.datasource_metadata.op("?")(literal("thread_id", type_=String())),
                Datasource.datasource_metadata.op("->>")(literal("thread_id", type_=String())) == literal(str(thread_uuid), type_=String())
            )
        ).order_by(desc(Datasource.created_at))  # Order by created_at DESC to get latest first
        result = await db.execute(stmt)
        all_datasources = result.scalars().all()

        # Group by filename and keep only the latest one (first in DESC order)
        seen_filenames = {}
        datasources = []
        for ds in all_datasources:
            filename_key = ds.filename or ds.name or "unknown"  # Use filename as key, fallback to name
            if filename_key not in seen_filenames:
                seen_filenames[filename_key] = True
                datasources.append(ds)  # Keep only the first (latest) occurrence
    else:
        # Get only channel-level datasources (exclude thread-level e.g. email attachments)
        # Thread-level datasources have datasource_metadata.thread_id set
        stmt = select(Datasource).where(
            and_(
                Datasource.channel_id == channel_id,
                or_(
                    Datasource.datasource_metadata.is_(None),
                    ~Datasource.datasource_metadata.op("?")(literal("thread_id", type_=String()))
                )
            )
        )
        result = await db.execute(stmt)
        datasources = result.scalars().all()

    # Categorize datasources by embedding status
    total_datasources = len(datasources)
    embedding_required = 0
    in_progress = 0
    completed = 0
    failed = 0
    not_required = 0

    datasource_list = []

    for ds in datasources:
        if ds.is_embedding_required:
            embedding_required += 1

        if ds.embedding_status == 0:
            not_required += 1
        elif ds.embedding_status == 1:
            in_progress += 1
        elif ds.embedding_status == 2:
            completed += 1
        elif ds.embedding_status == 3:
            failed += 1

        datasource_list.append({
            "id": str(ds.id),
            "name": ds.name,
            "filename": ds.filename,
            "is_embedding_required": ds.is_embedding_required,
            "embedding_status": ds.embedding_status,
            "error_message": ds.error_message,
            "created_at": ds.created_at,
            "updated_at": ds.updated_at
        })

    return EmbeddingStatusResponse(
        channel_id=channel_id,
        total_datasources=total_datasources,
        embedding_required=embedding_required,
        in_progress=in_progress,
        completed=completed,
        failed=failed,
        not_required=not_required,
        datasources=datasource_list
    )
