"""
Vault-integration helpers shared across datasource create/upload/bulk flows.

Private module: used by crud.py, upload.py, bulk.py, and processing.py.
"""

from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.giggso_vault import GiggsoVault
from app.services.vault_service import vault_service


async def get_vault_credentials_for_datasource(datasource, db: AsyncSession) -> Optional[Dict[str, Any]]:
    """
    Resolve vault by datasource_id (via datasource.giggso_vault_id), open vault and return stored credentials.
    Returns the full payload from vault (contains 'credentials' and possibly file_url, file_path, etc.).
    """
    if not getattr(datasource, "giggso_vault_id", None):
        return None
    vault_stmt = select(GiggsoVault).where(GiggsoVault.giggso_vault_id == datasource.giggso_vault_id)
    vault_result = await db.execute(vault_stmt)
    vault_record = vault_result.scalar_one_or_none()
    if not vault_record or not vault_record.vault_unique_id:
        return None
    vault_data = await vault_service.retrieve_from_vault(vault_record.vault_unique_id)
    return vault_data


async def handle_vault_integration(
    datasource_metadata: Dict[str, Any],
    user_id: str,
    company_id: str,
    db: AsyncSession,
    required: bool = True
) -> Optional[str]:
    """
    Handle vault integration for datasource metadata

    Args:
        datasource_metadata: Complete datasource metadata dictionary (after cleanup)
        user_id: User ID
        company_id: Company ID
        db: Database session
        required: If True, vault failure will raise HTTPException. If False, returns None on failure.

    Returns:
        giggso_vault_id (UUID) if vault save successful, None if vault save failed and not required

    Raises:
        HTTPException: If vault integration fails and vault is required
    """
    if not datasource_metadata:
        return None

    # Generate vault unique ID
    vault_unique_id = vault_service.generate_vault_unique_id(str(user_id), "datasource")

    # Save entire metadata to vault (no transformation)
    saved_vault_id = await vault_service.save_to_vault(datasource_metadata, vault_unique_id)

    # If vault save failed, handle based on required flag
    if not saved_vault_id:
        if required:
            print(f"Vault save failed for ID: {vault_unique_id} - cannot proceed with datasource creation")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to save sensitive data to vault. Datasource creation cannot proceed without secure storage."
            )
        else:
            print(f"Vault save failed for ID: {vault_unique_id} - continuing without vault integration")
            return None

    # Only create vault record if external vault save was successful
    try:
        # Create a shorter vault label that fits within 50 characters
        base_label = f"ds_{vault_unique_id[:8]}"  # Use first 8 chars of vault_unique_id
        vault_label = f"{base_label}_ok"  # External vault save successful

        vault_record = GiggsoVault(
            vault_unique_id=vault_unique_id,
            user_id=user_id,  # Store as UUID string
            vault_label=vault_label,
            vault_type="datasource_metadata",
            company_id=company_id,  # Store as UUID string
            created_by=user_id,  # Store as UUID string
            created_datetime=datetime.utcnow()
        )

        db.add(vault_record)
        # Flush to ensure the record is sent to the database before commit
        # This is important for Oracle and other databases that require explicit flushing
        await db.flush()
        await db.commit()
        print(f"Committed vault record to database: {vault_unique_id}")

        # Refresh to get the generated UUID
        await db.refresh(vault_record)

        # This ensures the commit persisted, especially important for Oracle databases
        verify_stmt = select(GiggsoVault).where(
            GiggsoVault.vault_unique_id == vault_unique_id
        )
        verify_result = await db.execute(verify_stmt)
        verified_record = verify_result.scalar_one_or_none()

        if not verified_record:
            # Try to query by giggso_vault_id as well
            id_verify_stmt = select(GiggsoVault).where(
                GiggsoVault.giggso_vault_id == vault_record.giggso_vault_id
            )
            id_verify_result = await db.execute(id_verify_stmt)
            id_verified_record = id_verify_result.scalar_one_or_none()

            if id_verified_record:
                print(f"WARNING: Record found by giggso_vault_id but not by vault_unique_id")
                print(f"WARNING: Found record vault_unique_id: {id_verified_record.vault_unique_id}")
            else:
                print(f"ERROR: Record not found by giggso_vault_id either")

            raise Exception(f"Vault record commit verification failed: Record with vault_unique_id '{vault_unique_id}' not found after commit. This indicates the commit did not persist.")

        print(f"✅ Verified vault record exists in database: {vault_unique_id}, giggso_vault_id: {verified_record.giggso_vault_id}")
        print(f"Successfully stored credentials in vault. Vault ID: {vault_unique_id}")
        print(f"External vault save successful, created database record with ID: {vault_unique_id}")

        # Return both giggso_vault_id (UUID) and vault_unique_id (string)
        return {
            "giggso_vault_id": vault_record.giggso_vault_id,
            "vault_unique_id": vault_unique_id
        }

    except Exception as e:
        # Rollback the transaction if commit failed
        try:
            await db.rollback()
        except:
            pass  # Ignore rollback errors

        print(f"Failed to create vault record in database: {str(e)}")
        # If database creation fails, we can't proceed - this is a critical error
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Critical error: Failed to create vault record in database: {str(e)}"
        )
