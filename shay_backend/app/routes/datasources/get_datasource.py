"""
Datasource GET /{datasource_id} endpoint.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.channel import Channel
from app.models.datasource import Datasource
from app.schemas.datasource import DatasourceResponse

from ._embedding_helpers import _aryx_ingestion_status_for
from ._metadata_helpers import sanitize_datasource_metadata

router = APIRouter()


@router.get("/{datasource_id}", response_model=DatasourceResponse)
async def get_datasource(
    datasource_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> DatasourceResponse:
    """Get a specific datasource by ID"""
    user = await get_current_user_required(request)

    # Get datasource with channel
    stmt = select(Datasource).where(Datasource.id == datasource_id)
    result = await db.execute(stmt)
    datasource = result.scalar_one_or_none()

    if not datasource:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Datasource not found"
        )

    # Check permissions through channel
    if not datasource.is_accessible_by_user(user.company_id, user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to datasource"
        )

    # Get channel for workspace_id and company_id
    channel_stmt = select(Channel).where(Channel.id == datasource.channel_id)
    channel_result = await db.execute(channel_stmt)
    channel = channel_result.scalar_one_or_none()

    return DatasourceResponse(
        id=str(datasource.id),
        name=datasource.name,
        filename=datasource.filename,
        storage_type=datasource.storage_type,
        provider=datasource.provider,
        app_type=datasource.app_type,
        config=datasource.config,
        datasource_metadata=sanitize_datasource_metadata(datasource.datasource_metadata),
        file_size=datasource.file_size,
        file_type=datasource.file_type,
        file_url=datasource.file_url,
        channel_id=str(datasource.channel_id),
        workspace_id=str(channel.workspace_id) if channel else None,
        company_id=str(channel.company_id) if channel else None,
        added_by=str(datasource.added_by),
        is_active=datasource.is_active,
        is_connected=datasource.is_connected,
        is_processed=datasource.is_processed,
        processing_status=datasource.processing_status,
        error_message=datasource.error_message,
        last_processed_at=datasource.last_processed_at,
        processing_time=datasource.processing_time,
        record_count=datasource.record_count,
        # Pre-existing bug, unrelated to the Aryx integration: these two
        # fields are required (non-Optional) on DatasourceResponse but were
        # never passed here, so this endpoint 500'd on every call before this
        # fix — discovered only because it blocked testing aryx_ingestion_status
        # below. Values match how every other endpoint in this file populates them.
        is_embedding_required=datasource.is_embedding_required,
        embedding_status=datasource.embedding_status,
        created_at=datasource.created_at,
        updated_at=datasource.updated_at,
        # Additive: None for every datasource without an aryx.discovery_id
        # in its metadata — existing (non-Aryx) callers see no change. This
        # is the real "poll by ID" endpoint, so it's the one that reflects
        # LIVE status on every call, not just a snapshot at creation time.
        aryx_ingestion_status=await _aryx_ingestion_status_for(datasource.datasource_metadata)
    )
