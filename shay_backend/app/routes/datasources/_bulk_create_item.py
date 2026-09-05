"""
Per-item processing for bulk_create.py (POST /bulk).

Private module: extracted verbatim (per-datasource loop body) from the
original create_datasources_bulk endpoint, now split into name-resolution
and vault+persist steps (see the sibling _bulk_create_*.py files) so no
single file holds the whole thing. Each expected failure is raised as
BulkItemFailure so the caller's loop can append it to failed_datasources
with the exact same message text as before.
"""

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.channel import Channel
from app.models.datasource import Datasource
from app.services.vault_data_builder import enhance_datasource_metadata

from ._bulk_create_name_resolution import resolve_bulk_name_and_filename
from ._bulk_create_persist import save_bulk_create_item_with_vault
from ._bulk_item_failure import BulkItemFailure
from ._metadata_generator import generate_datasource_metadata
from ._metadata_helpers import clean_metadata


async def process_bulk_create_item(datasource_data, user, db: AsyncSession) -> dict:
    """Process a single bulk-create datasource item. Returns the created_datasources entry dict."""
    # Get channel
    stmt = select(Channel).where(Channel.id == datasource_data.channel_id)
    result = await db.execute(stmt)
    channel = result.scalar_one_or_none()

    if not channel:
        raise BulkItemFailure(datasource_data.name, "Channel not found")

    # Check permissions
    if not channel.is_accessible_by_user(user.company_id, user.role):
        raise BulkItemFailure(datasource_data.name, "Access denied to channel")

    # Check for duplicate datasource in the same channel
    existing_datasource_stmt = select(Datasource).where(
        and_(
            Datasource.name == datasource_data.name,
            Datasource.channel_id == datasource_data.channel_id
        )
    )
    existing_datasource_result = await db.execute(existing_datasource_stmt)
    if existing_datasource_result.scalars().first():
        raise BulkItemFailure(
            datasource_data.name,
            f"Datasource with name '{datasource_data.name}' already exists in this channel"
        )

    # Validate storage type specific requirements
    if datasource_data.storage_type == "cloud" and not datasource_data.provider:
        raise BulkItemFailure(datasource_data.name, "Provider is required for cloud storage type")

    if datasource_data.storage_type == "app" and not datasource_data.app_type:
        raise BulkItemFailure(datasource_data.name, "App type is required for app storage type")

    # Handle app_provider mapping for app storage
    if datasource_data.storage_type == "app":
        if datasource_data.app_provider and not datasource_data.provider:
            datasource_data.provider = datasource_data.app_provider
        elif not datasource_data.app_provider and not datasource_data.provider:
            raise BulkItemFailure(datasource_data.name, "app_provider is required for app storage type")

    datasource_name, filename = resolve_bulk_name_and_filename(datasource_data)

    metadata = generate_datasource_metadata(
        filename=filename or "app_file",
        storage_type=datasource_data.storage_type,
        channel_id=datasource_data.channel_id,
        workspace_id=str(channel.workspace_id),
        user_id=str(user.id),
        file_size=datasource_data.file_size or 0,
        file_type=datasource_data.file_type or "application/octet-stream",
        provider=datasource_data.provider,
        app_type=datasource_data.app_type,
        log_type=datasource_data.log_type,
        config=datasource_data.config.dict() if datasource_data.config else None,
        file_url=datasource_data.file_url,
        is_embedding_required=datasource_data.is_embedding_required or False
    )
    cleaned_metadata = clean_metadata(metadata)

    enhanced_metadata = await enhance_datasource_metadata(
        existing_metadata=cleaned_metadata,
        storage_type=datasource_data.storage_type,
        provider=datasource_data.provider,
        config=datasource_data.config.dict() if datasource_data.config else None,
        app_type=getattr(datasource_data, 'app_type', None),
        db=db,
        channel_id=datasource_data.channel_id,
        location=getattr(datasource_data, 'location', None),
        accessToken=getattr(datasource_data, 'accessToken', None)
    )

    return await save_bulk_create_item_with_vault(
        datasource_data=datasource_data,
        datasource_name=datasource_name,
        filename=filename,
        enhanced_metadata=enhanced_metadata,
        channel=channel,
        user=user,
        db=db,
    )
