"""
Datasource list endpoint (GET /).

Stated exception (162 lines): the endpoint independently supports
channel-level and thread-level (dedup-by-filename) pagination paths on top
of ~8 optional filters; the shared filter-building and row-building were
already extracted to _list_filters.py / _list_response_builder.py, and
further splitting the two pagination branches would fragment one cohesive
control flow without reducing real duplication.
"""

import uuid
from typing import Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.channel import Channel
from app.models.channel_member import ChannelMember
from app.models.datasource import Datasource
from app.schemas.datasource import DatasourceListWithRelations
from app.utils.channel_access import check_channel_access, check_channel_access_by_thread

from ._list_filters import build_common_datasource_filters
from ._list_response_builder import build_datasource_list_rows, fetch_channel_membership_map

router = APIRouter()


@router.get("/", response_model=DatasourceListWithRelations)
async def list_datasources(
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    channel_id: Optional[str] = None,
    thread_id: Optional[str] = Query(None, description="Filter by thread ID. When set, returns only thread-level datasources for this thread. When omitted, channel-level list excludes thread-level (e.g. email attachment) datasources."),
    storage_type: Optional[str] = Query(None, description="Filter by storage type: local, cloud, db, app"),
    data_source_type: Optional[str] = Query(None, description="Alias for storage_type. Filter by data source type: local, cloud, db, app"),
    provider: Optional[str] = None,
    app_type: Optional[str] = None,
    processing_status: Optional[str] = None,
    is_connected: Optional[bool] = Query(None, description="Filter by connection status. True for connected, False for disconnected"),
    search: Optional[str] = None
) -> DatasourceListWithRelations:
    """List datasources with filtering and pagination

    Supports filtering by data source type (storage_type or data_source_type):
    - local: Local file uploads
    - cloud: Cloud storage (S3, Azure, etc.)
    - db: Database connections
    - app: App-based sources (Google Drive, SharePoint, etc.)

    Thread-level vs channel-level: Attachment datasources from email sync are stored as
    thread-level (datasource_metadata.thread_id set). When listing by channel without
    thread_id, only channel-level datasources are returned. Pass thread_id to get
    datasources for a specific thread (e.g. email attachments in that thread).
    """
    user = await get_current_user_required(request)

    if channel_id:
        await check_channel_access(db, user, channel_id)

    channel_uuid = None
    if channel_id:
        try:
            channel_uuid = uuid.UUID(channel_id) if isinstance(channel_id, str) else channel_id
        except (ValueError, AttributeError):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid channel_id format: {channel_id}"
            )

    thread_uuid = None
    if thread_id:
        try:
            thread_uuid = uuid.UUID(thread_id)
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid thread_id format: {thread_id}"
            )
        await check_channel_access_by_thread(db, user, thread_id)

    type_filter = data_source_type if data_source_type else storage_type

    filters = build_common_datasource_filters(
        thread_uuid=thread_uuid,
        channel_uuid=channel_uuid,
        type_filter=type_filter,
        provider=provider,
        app_type=app_type,
        processing_status=processing_status,
        is_connected=is_connected,
        search=search,
    )

    membership_join = and_(
        ChannelMember.channel_id == Datasource.channel_id,
        ChannelMember.user_id == user.id,
        ChannelMember.is_active == True,
    )

    base_query = (
        select(Datasource)
        .join(Datasource.channel)
        .where(Channel.company_id == user.company_id)
        .join(ChannelMember, membership_join)
        .where(*filters)
    )
    count_query = (
        select(func.count(Datasource.id))
        .join(Datasource.channel)
        .where(Channel.company_id == user.company_id)
        .join(ChannelMember, membership_join)
        .where(*filters)
    )

    # Get total count - same as main query: company + channel membership
    count_result = await db.execute(count_query)
    total_count = count_result.scalar()

    # Apply pagination and ordering (tie-break by id so "latest" is deterministic for same created_at)
    query = base_query.order_by(desc(Datasource.created_at), desc(Datasource.id))

    # For thread-level queries: deduplicate by filename; prefer embedding-completed when present, else latest
    # Same file can appear in multiple emails; return one row per filename so no duplicates
    if thread_uuid:
        result = await db.execute(query)
        all_datasources = result.scalars().all()

        # Sort: embedding_status==2 (completed) first, then by created_at desc, then id desc
        # So per filename we keep: completed row if any, else the latest row
        def _thread_ds_sort_key(ds) -> Tuple[int, float, str]:
            ts = ds.created_at.timestamp() if ds.created_at else 0
            return (0 if (ds.embedding_status == 2) else 1, -ts, str(ds.id or ""))

        all_datasources_sorted = sorted(all_datasources, key=_thread_ds_sort_key)
        seen_filenames = {}
        unique_datasources = []
        for ds in all_datasources_sorted:
            filename_key = (ds.filename or ds.name or "unknown").strip() or "unknown"
            if filename_key not in seen_filenames:
                seen_filenames[filename_key] = True
                unique_datasources.append(ds)

        total_count = len(unique_datasources)
        start_idx = (page - 1) * size
        end_idx = start_idx + size
        datasources = unique_datasources[start_idx:end_idx]
    else:
        # For channel-level queries: apply pagination normally
        query = query.offset((page - 1) * size).limit(size)
        result = await db.execute(query)
        datasources = result.scalars().all()

    members_map = await fetch_channel_membership_map(db, user, datasources)
    datasource_responses = await build_datasource_list_rows(datasources, members_map, db)

    return DatasourceListWithRelations(
        datasources=datasource_responses,
        total=total_count,
        page=page,
        size=size,
        pages=(total_count + size - 1) // size
    )
