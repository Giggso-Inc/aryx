"""
Datasource DELETE /{datasource_id} endpoint.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.datasource import Datasource
from app.models.giggso_vault import GiggsoVault
from app.services.ml_service import ml_service

logger = logging.getLogger(__name__)

router = APIRouter()


@router.delete("/{datasource_id}")
async def delete_datasource(
    datasource_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> dict:
    """Delete a specific datasource"""
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

    if datasource.is_embedding_required and datasource.giggso_vault_id:
        try:
            # Get vault_unique_id from gg_vault table
            vault_stmt = select(GiggsoVault).where(GiggsoVault.giggso_vault_id == datasource.giggso_vault_id)
            vault_result = await db.execute(vault_stmt)
            vault_record = vault_result.scalar_one_or_none()

            if not vault_record or not vault_record.vault_unique_id:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Vault record not found for datasource. Cannot delete embeddings."
                )

            # Determine embedding type based on file type, storage type, and provider
            from app.services.ml_service import get_embedd_type_from_file_type
            embedding_type = get_embedd_type_from_file_type(
                file_type=datasource.file_type,
                storage_type=datasource.storage_type,
                provider=datasource.provider
            )

            # Extract JWT token from Authorization header (if available)
            auth_header = request.headers.get("Authorization")
            jwt_token = None
            if auth_header and auth_header.startswith("Bearer "):
                jwt_token = auth_header.split(" ")[1]

            logger.info(f"Deleting embeddings for datasource {datasource_id}, embedding_type: {embedding_type}")

            # Call ML API to delete embeddings
            delete_result = await ml_service.delete_embeddings(
                channel_id=str(datasource.channel_id),
                data_sources_vault_tokens=[vault_record.vault_unique_id],
                embedding_type=embedding_type,
                jwt_token=jwt_token
            )

            # If delete embeddings API call failed, fail the entire deletion
            if not delete_result.get("success", False):
                error_message = delete_result.get("error") or delete_result.get("message", "Unknown error")
                logger.error(f"Failed to delete embeddings for datasource {datasource_id}: {error_message}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to delete embeddings: {error_message}"
                )

            logger.info(f"Successfully deleted embeddings for datasource {datasource_id}")

        except HTTPException:
            # Re-raise HTTPException (already formatted)
            raise
        except Exception as e:
            logger.error(f"Error deleting embeddings for datasource {datasource_id}: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to delete embeddings: {str(e)}"
            )

    await db.delete(datasource)
    await db.commit()

    return {"message": "Datasource deleted successfully"}
