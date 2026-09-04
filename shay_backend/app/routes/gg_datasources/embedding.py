"""
Embedding-status / ML-webhook endpoints:

  GET    /embedding-status/{scope_level}/{scope_id}
  POST   /embedding/webhook              ML callback (no auth — called by the ML service)
  POST   /embedding/regenerate/{datasource_id}
"""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.gg_datasource import GGDatasource
from app.schemas.gg_datasource import (
    GGEmbeddingStatusResponse,
    MLWebhookRequest,
    MLWebhookResponse,
    RegenerateEmbeddingResponse,
)
from app.services.ml_service import ml_service

router = APIRouter()


@router.get("/embedding-status/{scope_level}/{scope_id}", response_model=GGEmbeddingStatusResponse)
async def get_embedding_status(
    scope_level: str,
    scope_id:    str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> GGEmbeddingStatusResponse:
    """Get embedding status for all datasources at a given scope level."""
    await get_current_user_required(request, db)

    if scope_level not in ("workspace", "channel", "thread", "message"):
        raise HTTPException(status_code=400, detail="scope_level must be workspace | channel | thread | message")

    fk_col = {
        "workspace": GGDatasource.workspace_id,
        "channel":   GGDatasource.channel_id,
        "thread":    GGDatasource.thread_id,
        "message":   GGDatasource.message_id,
    }[scope_level]

    stmt = select(GGDatasource).where(
        and_(fk_col == UUID(scope_id), GGDatasource.level == scope_level)
    )
    datasources = (await db.execute(stmt)).scalars().all()

    total = len(datasources)
    emb_required = in_progress = completed = failed = not_required = 0
    ds_list = []

    for ds in datasources:
        if ds.is_embedding_required:
            emb_required += 1
        if ds.embedding_status == 0:
            not_required += 1
        elif ds.embedding_status == 1:
            in_progress += 1
        elif ds.embedding_status == 2:
            completed += 1
        elif ds.embedding_status == 3:
            failed += 1
        ds_list.append({
            "id":                    str(ds.id),
            "name":                  ds.name,
            "filename":              ds.filename,
            "is_embedding_required": ds.is_embedding_required,
            "embedding_status":      ds.embedding_status,
            "error_message":         ds.error_message,
            "created_at":            ds.created_at,
            "updated_at":            ds.updated_at,
        })

    return GGEmbeddingStatusResponse(
        scope_level=scope_level,
        scope_id=scope_id,
        total_datasources=total,
        embedding_required=emb_required,
        in_progress=in_progress,
        completed=completed,
        failed=failed,
        not_required=not_required,
        datasources=ds_list,
    )


@router.post("/embedding/webhook", response_model=MLWebhookResponse)
async def ml_embedding_webhook(
    webhook_data: MLWebhookRequest,
    db: AsyncSession = Depends(get_db),
) -> MLWebhookResponse:
    """Webhook endpoint for ML team to report embedding completion status."""
    try:
        vault_unique_ids = webhook_data.vaultUniqueIds
        emb_status = 2 if webhook_data.status == "success" else 3

        updated = 0
        failed_c = 0
        for vault_uid in vault_unique_ids:
            try:
                uuid_val = UUID(vault_uid)
                stmt = select(GGDatasource).where(GGDatasource.vault_unique_id == uuid_val)
                rows = (await db.execute(stmt)).scalars().all()
                for ds in rows:
                    ds.embedding_status = emb_status
                    if emb_status == 3:
                        ds.error_message = webhook_data.message or "Embedding processing failed"
                    else:
                        ds.error_message = None
                    ds.updated_at = datetime.utcnow()
                    updated += 1
            except Exception:
                failed_c += 1

        if updated:
            await db.commit()

        return MLWebhookResponse(
            message=f"Updated {updated} datasource(s)",
            processed_count=updated,
            failed_count=failed_c,
        )
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to process webhook: {exc}")


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
