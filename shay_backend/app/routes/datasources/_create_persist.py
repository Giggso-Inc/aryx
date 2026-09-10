"""
Vault-integration + row-persist helper for create.py (POST / — single
datasource creation).

Private module: extracted verbatim from the original create_datasource
endpoint body.
"""

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select

from app.models.datasource import Datasource
from app.models.giggso_vault import GiggsoVault

from ._vault_helpers import handle_vault_integration


async def save_new_datasource_with_vault(
    datasource_data, datasource_name: str, filename: str, cleaned_metadata: dict, channel, user, db
) -> Datasource:
    """Handle vault integration, persist the new Datasource row, and verify the
    vault record survived the commit. Raises HTTPException on any failure.
    """
    vault_unique_id = None
    giggso_vault_id = None
    if cleaned_metadata:
        # For cloud and database datasources (which contain sensitive credentials), vault integration is required
        # For local file uploads, vault integration is optional
        vault_required = datasource_data.storage_type in ["cloud", "database", "app"]
        try:
            vault_result = await handle_vault_integration(
                datasource_metadata=cleaned_metadata,
                user_id=str(user.id),
                company_id=str(channel.company_id),
                db=db,
                required=vault_required
            )
            vault_unique_id = vault_result["vault_unique_id"] if vault_result else None
            giggso_vault_id = vault_result["giggso_vault_id"] if vault_result else None
        except HTTPException:
            raise
        except Exception as e:
            print(f"Unexpected error during vault integration: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to integrate with vault service"
            )

    # Store cleaned metadata directly in database (with vault integration for backup)
    final_metadata = cleaned_metadata.copy()
    if vault_unique_id:
        final_metadata["vault_unique_id"] = str(vault_unique_id)

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
        giggso_vault_id=giggso_vault_id,  # Store vault ID in dedicated column
        file_size=datasource_data.file_size,
        file_type=datasource_data.file_type,
        file_url=datasource_data.file_url,
        channel_id=datasource_data.channel_id,
        added_by=user.id,
        is_embedding_required=datasource_data.is_embedding_required or False,
        embedding_status=1 if (datasource_data.is_embedding_required or False) else 0
    )

    db.add(datasource)
    # Flush to ensure the record is sent to the database before commit
    # This is important for Oracle and other databases that require explicit flushing
    await db.flush()
    await db.commit()
    await db.refresh(datasource)

    # Verify vault record still exists after datasource creation
    # This ensures the vault record commit persisted and wasn't rolled back
    if vault_unique_id:
        vault_verify_stmt = select(GiggsoVault).where(GiggsoVault.vault_unique_id == vault_unique_id)
        vault_verify_result = await db.execute(vault_verify_stmt)
        if not vault_verify_result.scalar_one_or_none():
            print(f"ERROR: Vault record {vault_unique_id} not found after datasource creation!")
            print(f"ERROR: This indicates the vault record commit was rolled back or did not persist")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Critical error: Vault record was lost after datasource creation. Vault ID: {vault_unique_id}"
            )
        print(f"✅ Verified vault record still exists after datasource creation: {vault_unique_id}")

    return datasource
