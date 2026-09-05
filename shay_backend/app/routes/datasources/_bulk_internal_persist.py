"""
Vault-integration + row-persist for the internal/bulk per-item loop.

Private module: used only by _bulk_internal_create_item.py.
"""

import logging
import uuid

from fastapi import HTTPException

from app.models.datasource import Datasource

from ._bulk_item_failure import BulkItemFailure
from ._metadata_helpers import sanitize_datasource_metadata
from ._vault_helpers import handle_vault_integration

logger = logging.getLogger(__name__)


async def save_internal_bulk_item_with_vault(
    *, datasource_data, filename, datasource_name, enhanced_metadata, thread, thread_uuid, channel, user, db,
) -> dict:
    """Handle vault integration, persist the Datasource row, and build the
    created_datasources entry dict for an internal/bulk item.
    """
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

            if not vault_unique_id:
                raise BulkItemFailure(
                    datasource_data.name or "Unknown",
                    "Vault integration failed. Cannot create datasource without secure storage."
                )
        except BulkItemFailure:
            raise
        except Exception as e:
            if isinstance(e, HTTPException):
                raise BulkItemFailure(datasource_data.name or "Unknown", f"Vault integration failed: {e.detail}")
            logger.error(f"Unexpected error during vault integration: {str(e)}", exc_info=True)
            raise BulkItemFailure(datasource_data.name or "Unknown", "Failed to integrate with vault service")

    final_metadata = enhanced_metadata.copy()
    if vault_unique_id:
        final_metadata["vault_unique_id"] = str(vault_unique_id)

    # Create datasource
    datasource = Datasource(
        id=str(uuid.uuid4()),
        name=datasource_name,
        filename=filename,
        storage_type=datasource_data.storage_type,
        provider=datasource_data.provider,
        app_type=datasource_data.app_type,
        log_type=datasource_data.log_type,
        config=datasource_data.config.dict() if datasource_data.config else None,
        datasource_metadata=final_metadata,
        giggso_vault_id=giggso_vault_id,
        file_size=datasource_data.file_size or 0,
        file_type=datasource_data.file_type or "application/octet-stream",
        file_url=datasource_data.file_url,
        channel_id=thread.channel_id,
        added_by=user.id,
        is_embedding_required=datasource_data.is_embedding_required or False,
        embedding_status=1 if (datasource_data.is_embedding_required or False) else 0
    )

    db.add(datasource)
    await db.commit()
    await db.refresh(datasource)

    logger.info(f"✅ Created datasource: {datasource_name} (id={datasource.id}, thread_id={thread_uuid})")

    return {
        "id": str(datasource.id),
        "name": datasource.name,
        "filename": datasource.filename,
        "storage_type": datasource.storage_type,
        "provider": datasource.provider,
        "app_type": datasource.app_type,
        "config": datasource.config,
        "datasource_metadata": sanitize_datasource_metadata(datasource.datasource_metadata),
        "giggso_vault_id": str(datasource.giggso_vault_id) if datasource.giggso_vault_id else None,
        "file_size": datasource.file_size,
        "file_type": datasource.file_type,
        "file_url": datasource.file_url,
        "channel_id": str(datasource.channel_id),
        "workspace_id": str(thread.workspace_id),
        "company_id": str(channel.company_id),
        "added_by": str(datasource.added_by),
        "is_active": datasource.is_active,
        "is_connected": datasource.is_connected,
        "is_processed": datasource.is_processed,
        "processing_status": datasource.processing_status,
        "error_message": datasource.error_message,
        "last_processed_at": datasource.last_processed_at,
        "processing_time": datasource.processing_time,
        "record_count": datasource.record_count,
        "is_embedding_required": datasource.is_embedding_required,
        "embedding_status": datasource.embedding_status,
        "created_at": datasource.created_at,
        "updated_at": datasource.updated_at
    }
