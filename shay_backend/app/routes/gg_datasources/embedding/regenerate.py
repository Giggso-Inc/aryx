"""POST /embedding/regenerate/{datasource_id} — re-trigger embedding."""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.gg_datasource import GGDatasource
from app.schemas.gg_datasource import RegenerateEmbeddingResponse
from app.services.ml_service import ml_service

router = APIRouter()


@router.post("/embedding/regenerate/{datasource_id}", response_model=RegenerateEmbeddingResponse)
async def regenerate_embedding(
    datasource_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> RegenerateEmbeddingResponse:
    """Re-trigger embedding for a specific GGDatasource."""
    user = await get_current_user_required(request, db)

    ds = (await db.execute(select(GGDatasource).where(GGDatasource.id == UUID(datasource_id)))).scalar_one_or_none()
    if not ds:
        raise HTTPException(status_code=404, detail="Datasource not found")

    if str(ds.added_by) != str(user.id):
        raise HTTPException(status_code=403, detail="You don't have permission to regenerate embedding for this datasource")

    if not ds.vault_unique_id:
        raise HTTPException(status_code=400, detail="Datasource does not have vault integration. Cannot regenerate embedding.")

    ds.embedding_status = 1  # in progress
    ds.updated_at = datetime.utcnow()
    await db.commit()

    try:
        from app.services.ml_service import get_embedd_type_from_file_type
        embedd_type = get_embedd_type_from_file_type(
            file_type=ds.file_type,
            storage_type=ds.storage_type,
            provider=ds.provider,
        )

        table_name = None
        if ds.datasource_metadata and isinstance(ds.datasource_metadata, dict):
            table_name = ds.datasource_metadata.get("tableName")

        auth_header = request.headers.get("Authorization")
        jwt_token = auth_header.split(" ")[1] if auth_header and auth_header.startswith("Bearer ") else None

        scope_id = str(
            ds.channel_id or ds.workspace_id or ds.thread_id or ds.message_id
        )

        await ml_service.request_embedding_processing(
            vault_unique_ids=[str(ds.vault_unique_id)],
            user_id=str(user.id),
            company_id=str(user.company_id),
            channel_id=scope_id,
            embedded_vault_unique_ids=[],
            jwt_token=jwt_token,
            embedd_type=embedd_type,
            table_name=table_name,
            table_names=None,
            openai_vault_token=None,
        )

        return RegenerateEmbeddingResponse(
            success=True,
            message="Embedding regeneration triggered successfully",
            datasource_id=datasource_id,
            embedding_status=1,
            status_description="in_progress",
        )
    except Exception as exc:
        ds.embedding_status = 3
        ds.error_message    = str(exc)
        ds.updated_at       = datetime.utcnow()
        await db.commit()
        return RegenerateEmbeddingResponse(
            success=False,
            message=f"Failed to trigger embedding: {exc}",
            datasource_id=datasource_id,
            embedding_status=3,
            status_description="failed",
        )
