"""
Datasource POST / (single-datasource create) endpoint.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.channel import Channel
from app.models.datasource import Datasource
from app.schemas.datasource import DatasourceCreate, DatasourceResponse
from app.services.vault_data_builder import enhance_datasource_metadata

from ._create_embedding_trigger import trigger_embedding_for_new_datasource
from ._create_name_resolution import resolve_create_name_and_filename
from ._create_persist import save_new_datasource_with_vault
from ._metadata_generator import generate_datasource_metadata
from ._metadata_helpers import clean_metadata, sanitize_datasource_metadata

router = APIRouter()


@router.post("/", response_model=DatasourceResponse)
async def create_datasource(
    datasource_data: DatasourceCreate,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> DatasourceResponse:
    """Create a single datasource"""
    user = await get_current_user_required(request)

    # Get channel
    stmt = select(Channel).where(Channel.id == datasource_data.channel_id)
    result = await db.execute(stmt)
    channel = result.scalar_one_or_none()

    if not channel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found")

    # Check permissions
    if not channel.is_accessible_by_user(user.company_id, user.role):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to channel")

    # Check for duplicate datasource in the same channel
    existing_datasource_stmt = select(Datasource).where(
        and_(
            Datasource.name == datasource_data.name,
            Datasource.channel_id == datasource_data.channel_id
        )
    )
    existing_datasource_result = await db.execute(existing_datasource_stmt)
    if existing_datasource_result.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Datasource with name '{datasource_data.name}' already exists in this channel"
        )

    # Validate storage type specific requirements
    if datasource_data.storage_type == "cloud" and not datasource_data.provider:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Provider is required for cloud storage type")

    if datasource_data.storage_type == "app" and not datasource_data.app_type:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="App type is required for app storage type")

    datasource_name, filename = resolve_create_name_and_filename(datasource_data)

    # Generate metadata structure (now with extracted filename)
    metadata = generate_datasource_metadata(
        filename=filename,
        storage_type=datasource_data.storage_type,
        channel_id=datasource_data.channel_id,
        workspace_id=str(channel.workspace_id),
        user_id=str(user.id),
        file_size=datasource_data.file_size,
        file_type=datasource_data.file_type,
        provider=datasource_data.provider,
        app_type=datasource_data.app_type,
        log_type=datasource_data.log_type,
        config=datasource_data.config.dict() if datasource_data.config else None,
        file_url=datasource_data.file_url,
        is_embedding_required=datasource_data.is_embedding_required or False
    )
    cleaned_metadata = clean_metadata(metadata)

    # Enhance metadata for database, cloud, and app storage types (all require vault integration)
    if datasource_data.storage_type in ["database", "cloud", "app"]:
        cleaned_metadata = await enhance_datasource_metadata(
            existing_metadata=cleaned_metadata,
            storage_type=datasource_data.storage_type,
            provider=datasource_data.provider,
            config=datasource_data.config.dict() if datasource_data.config else None,
            app_type=datasource_data.app_type,
            db=db,
            channel_id=datasource_data.channel_id,
            location=datasource_data.location,
            accessToken=datasource_data.accessToken
        )

    # Handle vault integration, persist the row, and verify the vault record survived the commit
    datasource = await save_new_datasource_with_vault(
        datasource_data, datasource_name, filename, cleaned_metadata, channel, user, db
    )

    # Trigger embedding if required
    await trigger_embedding_for_new_datasource(datasource, request, user, db)

    return DatasourceResponse(
        id=str(datasource.id),
        name=datasource.name,
        filename=datasource.filename,
        storage_type=datasource.storage_type,
        provider=datasource.provider,
        app_type=datasource.app_type,
        config=datasource.config,
        datasource_metadata=sanitize_datasource_metadata(datasource.datasource_metadata),
        giggso_vault_id=str(datasource.giggso_vault_id) if datasource.giggso_vault_id else None,
        file_size=datasource.file_size,
        file_type=datasource.file_type,
        file_url=datasource.file_url,
        channel_id=str(datasource.channel_id),
        workspace_id=str(channel.workspace_id),
        company_id=str(channel.company_id),
        added_by=str(datasource.added_by),
        is_active=datasource.is_active,
        is_connected=datasource.is_connected,
        is_processed=datasource.is_processed,
        processing_status=datasource.processing_status,
        error_message=datasource.error_message,
        last_processed_at=datasource.last_processed_at,
        processing_time=datasource.processing_time,
        record_count=datasource.record_count,
        is_embedding_required=datasource.is_embedding_required,
        embedding_status=datasource.embedding_status,
        created_at=datasource.created_at,
        updated_at=datasource.updated_at
    )
