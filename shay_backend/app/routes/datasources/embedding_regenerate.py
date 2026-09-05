"""
Datasource POST /embedding/regenerate/{datasource_id} endpoint.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.datasource import Datasource
from app.models.giggso_vault import GiggsoVault
from app.schemas.datasource import RegenerateEmbeddingResponse

from ._embedding_helpers import get_completed_embeddings_by_channel, get_openai_vault_token_for_company
from ._regenerate_ml_call import call_ml_and_emit_socket_for_regenerate

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/embedding/regenerate/{datasource_id}", response_model=RegenerateEmbeddingResponse)
async def regenerate_embedding(
    datasource_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> RegenerateEmbeddingResponse:
    """Regenerate embedding for a specific datasource"""
    try:
        # Get current user from authentication
        user = await get_current_user_required(request)
        current_user_id = str(user.id)
        current_company_id = str(user.company_id)

        # Find the datasource
        stmt = select(Datasource).where(Datasource.id == datasource_id)
        result = await db.execute(stmt)
        datasource = result.scalar_one_or_none()

        if not datasource:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Datasource not found")

        # Check if user has access to this datasource
        if str(datasource.added_by) != current_user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to regenerate embedding for this datasource"
            )

        # Check if datasource has vault integration
        if not datasource.giggso_vault_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Datasource does not have vault integration. Cannot regenerate embedding."
            )

        # Get vault_unique_id from gg_vault table
        vault_stmt = select(GiggsoVault).where(GiggsoVault.giggso_vault_id == datasource.giggso_vault_id)
        vault_result = await db.execute(vault_stmt)
        vault_record = vault_result.scalar_one_or_none()

        if not vault_record or not vault_record.vault_unique_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Vault record not found. Cannot regenerate embedding."
            )

        # Update embedding status to "in progress"
        datasource.embedding_status = 1  # 1 = in progress
        await db.commit()

        logger.info("=" * 80)
        logger.info("🔄 REGENERATING EMBEDDING")
        logger.info("=" * 80)
        logger.info(f"📋 Datasource ID: {datasource_id}")
        logger.info(f"🔑 giggso_vault_id: {datasource.giggso_vault_id}")
        logger.info(f"📦 vault_unique_id: {vault_record.vault_unique_id}")
        logger.info(f"👤 User ID: {current_user_id}")
        logger.info(f"🏢 Company ID: {current_company_id}")
        logger.info("=" * 80)

        # Determine embedd_type based on file type
        from app.services.ml_service import get_embedd_type_from_file_type
        embedd_type = get_embedd_type_from_file_type(
            file_type=datasource.file_type,
            storage_type=datasource.storage_type,
            provider=datasource.provider
        )

        logger.debug(f"Determined embedd_type: {embedd_type} for file_type: {datasource.file_type}, storage_type: {datasource.storage_type}, provider: {datasource.provider}")

        # Extract table_name from datasource metadata (for database datasources)
        table_name = None
        if datasource.datasource_metadata and isinstance(datasource.datasource_metadata, dict):
            table_name = datasource.datasource_metadata.get("tableName")

        # Get completed embeddings for this channel
        embedded_vault_unique_ids = await get_completed_embeddings_by_channel(str(datasource.channel_id), db)

        # Extract JWT token from Authorization header
        auth_header = request.headers.get("Authorization")
        jwt_token = None
        if auth_header and auth_header.startswith("Bearer "):
            jwt_token = auth_header.split(" ")[1]

        # Fetch OpenAI vault token (gpt_token) for company to send to ML API
        openai_vault_token = await get_openai_vault_token_for_company(db, current_company_id)

        # Call ML service directly and emit socket events based on the result
        await call_ml_and_emit_socket_for_regenerate(
            datasource=datasource,
            datasource_id=datasource_id,
            embedd_type=embedd_type,
            table_name=table_name,
            vault_unique_id=vault_record.vault_unique_id,
            current_user_id=current_user_id,
            current_company_id=current_company_id,
            embedded_vault_unique_ids=embedded_vault_unique_ids,
            jwt_token=jwt_token,
            openai_vault_token=openai_vault_token,
        )

        return RegenerateEmbeddingResponse(
            success=True,
            message="Embedding regeneration initiated successfully",
            datasource_id=datasource_id,
            embedding_status=1,
            status_description="in_progress"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Regenerate embedding error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to regenerate embedding: {str(e)}"
        )
