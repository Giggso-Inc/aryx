"""
Metadata build + vault-enhance step for the internal/bulk per-item loop.

Private module: used only by _bulk_internal_create_item.py.
"""

from app.services.vault_data_builder import enhance_datasource_metadata

from ._bulk_internal_file_path import resolve_vault_storage_type_and_file_path
from ._metadata_generator import generate_datasource_metadata
from ._metadata_helpers import clean_metadata


async def build_internal_bulk_enhanced_metadata(datasource_data, filename, thread, thread_uuid, channel, user, db):
    """Generate, clean, and vault-enhance the metadata dict for an internal/bulk item."""
    # Generate metadata structure (use thread's channel_id)
    metadata = generate_datasource_metadata(
        filename=filename or "app_file",
        storage_type=datasource_data.storage_type,
        channel_id=str(thread.channel_id),
        workspace_id=str(thread.workspace_id),
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

    # Add thread_id to metadata for thread-level association
    metadata["thread_id"] = str(thread_uuid)
    # Ensure company_id is in metadata for embedding processing
    if "company_id" not in metadata:
        metadata["company_id"] = str(channel.company_id)

    cleaned_metadata = clean_metadata(metadata)

    # For internal/bulk API: vault_storage_type and file_path for email attachments (S3 or local)
    vault_storage_type, file_path = resolve_vault_storage_type_and_file_path(datasource_data)

    # Enhance metadata with vault-specific fields AFTER cleaning
    enhanced_metadata = await enhance_datasource_metadata(
        existing_metadata=cleaned_metadata,
        storage_type=vault_storage_type,  # Use vault_storage_type (may be "local" for email attachments)
        provider=datasource_data.provider,
        config=datasource_data.config.dict() if datasource_data.config else None,
        app_type=getattr(datasource_data, 'app_type', None),
        db=db,
        channel_id=str(thread.channel_id),
        location=getattr(datasource_data, 'location', None),
        accessToken=getattr(datasource_data, 'accessToken', None)
    )
    if enhanced_metadata:
        enhanced_metadata["thread_id"] = str(thread_uuid)
        enhanced_metadata["company_id"] = str(channel.company_id)  # Ensure company_id is in enhanced metadata

        # For email attachments treated as local storage: ensure databaseType matches storageType
        if vault_storage_type == "local":
            enhanced_metadata["databaseType"] = "local"
            # Add file_path to credentials if extracted from file_url (for S3/local storage)
            if file_path:
                if "credentials" not in enhanced_metadata:
                    enhanced_metadata["credentials"] = {}
                enhanced_metadata["credentials"]["file_path"] = file_path
            # Add file_url so Giggso-AI-ML can fetch directly (FILE_UPLOAD_ENV=local: LOCAL_FILES_URL + path)
            if datasource_data.file_url:
                enhanced_metadata["file_url"] = datasource_data.file_url

    return enhanced_metadata
