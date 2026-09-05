"""
Datasource /stats and /count endpoints.

Stated exception (182 lines): two endpoints share small helpers
(_parse_channel_uuid, _exclude_thread_level) already factored out; stats
itself independently aggregates 7 counts (total/active/processed/pending/
failed/size/storage-type/provider breakdowns), which is one cohesive report
rather than reusable sub-units, so it was kept alongside the much smaller
/count endpoint instead of forcing an artificial third file.
"""

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import String, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.expression import literal

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.channel import Channel
from app.models.datasource import Datasource
from app.schemas.datasource import (
    DatasourceStats,
    DatasourceTypeCount,
    DatasourceTypeCountResponse,
)

router = APIRouter()


def _parse_channel_uuid(channel_id: str):
    try:
        return uuid.UUID(channel_id) if isinstance(channel_id, str) else channel_id
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid channel_id format: {channel_id}"
        )


def _exclude_thread_level():
    return or_(
        Datasource.datasource_metadata.is_(None),
        ~Datasource.datasource_metadata.op("?")(literal("thread_id", type_=String()))
    )


@router.get("/stats", response_model=DatasourceStats)
async def get_datasource_stats(
    request: Request,
    db: AsyncSession = Depends(get_db),
    channel_id: Optional[str] = None
) -> DatasourceStats:
    """Get datasource statistics"""
    user = await get_current_user_required(request)

    # Build base query - filter by user's company through channel relationship
    base_query = select(Datasource).join(Datasource.channel).where(Channel.company_id == user.company_id)
    total_query = select(func.count(Datasource.id)).join(Datasource.channel).where(Channel.company_id == user.company_id)

    # Apply channel filter if provided
    if channel_id:
        channel_uuid = _parse_channel_uuid(channel_id)
        base_query = base_query.where(Datasource.channel_id == channel_uuid)
        total_query = total_query.where(Datasource.channel_id == channel_uuid)

    # Exclude thread-level datasources (e.g. email attachments) from channel stats
    # so channel-level stats show only channel-level datasources
    base_query = base_query.where(_exclude_thread_level())
    total_query = total_query.where(_exclude_thread_level())

    # Get total count
    total_result = await db.execute(total_query)
    total_count = total_result.scalar()

    # Get active count
    active_query = base_query.where(and_(Datasource.is_active == True))
    active_result = await db.execute(active_query)
    active_count = len(active_result.scalars().all())

    # Get processed count
    processed_query = base_query.where(and_(Datasource.is_processed == True))
    processed_result = await db.execute(processed_query)
    processed_count = len(processed_result.scalars().all())

    # Get pending count
    pending_query = base_query.where(and_(Datasource.processing_status == "pending"))
    pending_result = await db.execute(pending_query)
    pending_count = len(pending_result.scalars().all())

    # Get failed count
    failed_query = base_query.where(and_(Datasource.processing_status == "failed"))
    failed_result = await db.execute(failed_query)
    failed_count = len(failed_result.scalars().all())

    # Get total file size
    size_query = base_query.where(and_(Datasource.file_size.isnot(None)))
    size_result = await db.execute(size_query)
    datasources_with_size = size_result.scalars().all()
    total_file_size = sum(ds.file_size for ds in datasources_with_size if ds.file_size)

    # Get storage type distribution
    # Use select() with columns directly for Core query (not with_entities which is ORM-only)
    storage_types_query = select(
        Datasource.storage_type,
        func.count(Datasource.id).label('count')
    ).join(Datasource.channel).where(
        Channel.company_id == user.company_id
    ).group_by(Datasource.storage_type)

    if channel_id:
        storage_types_query = storage_types_query.where(Datasource.channel_id == channel_uuid)

    storage_types_query = storage_types_query.where(_exclude_thread_level())

    storage_types_result = await db.execute(storage_types_query)
    storage_types = {row.storage_type: row.count for row in storage_types_result}

    # Get provider distribution (for cloud storage)
    provider_query = base_query.where(and_(Datasource.provider.isnot(None)))
    provider_result = await db.execute(provider_query)
    providers = {}
    for datasource in provider_result.scalars().all():
        provider = datasource.provider
        providers[provider] = providers.get(provider, 0) + 1

    return DatasourceStats(
        total_datasources=total_count,
        active_datasources=active_count,
        processed_datasources=processed_count,
        pending_datasources=pending_count,
        failed_datasources=failed_count,
        total_file_size=total_file_size,
        storage_type_breakdown=storage_types,
        provider_breakdown=providers
    )


@router.get("/count", response_model=DatasourceTypeCountResponse)
async def get_datasource_type_count(
    request: Request,
    db: AsyncSession = Depends(get_db),
    channel_id: Optional[str] = None
) -> DatasourceTypeCountResponse:
    """Get count of connected data sources by type (local, cloud, db, app)"""
    user = await get_current_user_required(request)

    # Build base query - filter by user's company and connected status
    # Get counts grouped by storage_type
    count_query = select(
        Datasource.storage_type,
        func.count(Datasource.id).label('count')
    ).join(Datasource.channel).where(
        and_(
            Channel.company_id == user.company_id,
            Datasource.is_connected == True
        )
    ).group_by(Datasource.storage_type)

    if channel_id:
        channel_uuid = _parse_channel_uuid(channel_id)
        count_query = count_query.where(Datasource.channel_id == channel_uuid)

    # Exclude thread-level datasources (e.g. email attachments) from type count
    # so channel-level count shows only channel-level datasources
    count_query = count_query.where(_exclude_thread_level())

    # Execute query to get counts by type
    result = await db.execute(count_query)
    type_counts = {row.storage_type: row.count for row in result}

    # Define the data source types to include in response
    data_source_types = ["local", "cloud", "app", "db"]

    counts = []
    total_connected = 0

    # Build response with counts for each type (0 if not found)
    for ds_type in data_source_types:
        count = type_counts.get(ds_type, 0)
        total_connected += count
        counts.append(DatasourceTypeCount(type=ds_type, count=count))

    return DatasourceTypeCountResponse(
        counts=counts,
        total_connected=total_connected
    )
