"""
Datasource list endpoint (GET /).

Scope resolution (channel_id/thread_id parsing + access checks) and the
thread-level dedup-by-filename pagination path are further extracted to
_list_scope_resolution.py and _list_thread_dedup.py (Raven
style-compliance, wave B4). The shared filter-building and row-building
were already extracted to _list_filters.py / _list_response_builder.py;
what remains here is building the two queries and choosing between the
thread-dedup and normal-pagination branch.
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.channel import Channel
from app.models.channel_member import ChannelMember
from app.models.datasource import Datasource
from app.schemas.datasource import DatasourceListWithRelations

from ._list_filters import build_common_datasource_filters
from ._list_response_builder import build_datasource_list_rows, fetch_channel_membership_map
from ._list_scope_resolution import resolve_list_scope
from ._list_thread_dedup import dedupe_thread_datasources

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

    channel_uuid, thread_uuid = await resolve_list_scope(db, user, channel_id, thread_id)

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
        total_count, datasources = dedupe_thread_datasources(all_datasources, page, size)
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
