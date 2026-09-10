"""
Datasource PUT /{datasource_id} endpoint.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.channel import Channel
from app.models.datasource import Datasource
from app.schemas.datasource import DatasourceResponse, DatasourceUpdate

from ._metadata_helpers import sanitize_datasource_metadata

router = APIRouter()


@router.put("/{datasource_id}", response_model=DatasourceResponse)
async def update_datasource(
    datasource_id: str,
    datasource_data: DatasourceUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> DatasourceResponse:
    """Update a specific datasource"""
    user = await get_current_user_required(request)

    # Get datasource
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

    # Update fields if provided
    if datasource_data.name is not None:
        datasource.name = datasource_data.name

    if datasource_data.storage_type is not None:
        datasource.storage_type = datasource_data.storage_type

    if datasource_data.provider is not None:
        datasource.provider = datasource_data.provider

    if datasource_data.app_type is not None:
        datasource.app_type = datasource_data.app_type

    if datasource_data.log_type is not None:
        datasource.log_type = datasource_data.log_type

    if datasource_data.config is not None:
        # Update config directly (no vault integration for config updates)
        datasource.config = datasource_data.config.dict()

    if datasource_data.datasource_metadata is not None:
        datasource.datasource_metadata = datasource_data.datasource_metadata

    if datasource_data.is_active is not None:
        datasource.is_active = datasource_data.is_active

    if datasource_data.is_connected is not None:
        datasource.is_connected = datasource_data.is_connected

    await db.commit()
    await db.refresh(datasource)

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
        created_at=datasource.created_at,
        updated_at=datasource.updated_at
    )
