"""POST /embedding/webhook — ML callback (no auth — called by the ML service)."""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.gg_datasource import GGDatasource
from app.schemas.gg_datasource import MLWebhookRequest, MLWebhookResponse

router = APIRouter()


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
