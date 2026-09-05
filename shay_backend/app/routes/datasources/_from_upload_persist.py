"""
Vault-integration + row-persist + response-building helper for
from_upload.py (POST /from-upload).

Private module: extracted verbatim from the original
create_datasource_from_upload endpoint body.
"""

import uuid

from fastapi import HTTPException, status

from app.models.datasource import Datasource
from app.schemas.datasource import DatasourceResponse

from ._metadata_helpers import sanitize_datasource_metadata
from ._vault_helpers import handle_vault_integration


async def finalize_from_upload_datasource(
    *, enhanced_metadata, datasource_name, file, file_size, storage_type, provider, log_type,
    config, upload_result, channel_id, user, channel, db,
) -> DatasourceResponse:
    """Handle vault integration, persist the Datasource row, and build the response."""
    # Handle vault integration for datasource metadata
    # Vault integration is REQUIRED for ALL datasource types to ensure data security
    vault_unique_id = None
    giggso_vault_id = None
    if enhanced_metadata:
        try:
            vault_result = await handle_vault_integration(
                datasource_metadata=enhanced_metadata,
                user_id=str(user.id),
                company_id=str(channel.company_id),
                db=db,
                required=True
            )
            vault_unique_id = vault_result["vault_unique_id"] if vault_result else None
            giggso_vault_id = vault_result["giggso_vault_id"] if vault_result else None
        except HTTPException as e:
            raise e
        except Exception as e:
            print(f"Unexpected error during vault integration: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to integrate with vault service"
            )

    final_metadata = enhanced_metadata.copy()
    if vault_unique_id:
        final_metadata["vault_unique_id"] = str(vault_unique_id)

    datasource = Datasource(
        id=str(uuid.uuid4()),
        name=datasource_name,
        filename=file.filename,
        storage_type=storage_type,
        provider=provider,
        app_type=None,
        log_type=log_type,
        config=config,
        datasource_metadata=final_metadata,
        file_size=file_size,
        file_type=file.content_type or "application/octet-stream",
        file_url=upload_result["file_url"],
        channel_id=channel_id,
        added_by=user.id,
        giggso_vault_id=giggso_vault_id
    )

    db.add(datasource)
    await db.commit()
    await db.refresh(datasource)

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
        created_at=datasource.created_at,
        updated_at=datasource.updated_at
    )
