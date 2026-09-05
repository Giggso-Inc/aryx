"""
Datasource POST /embedding/webhook endpoint.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.datasource import MLWebhookRequest, MLWebhookResponse

router = APIRouter()


@router.post("/embedding/webhook", response_model=MLWebhookResponse)
async def ml_embedding_webhook(
    webhook_data: MLWebhookRequest,
    db: AsyncSession = Depends(get_db)
) -> MLWebhookResponse:
    """Webhook endpoint for ML team to report embedding completion status"""
    try:
        # TODO: Temporarily commented out status update logic
        # Update embedding status for the provided vault_unique_ids
        # vault_unique_ids = webhook_data.vaultUniqueIds
        # status = 2 if webhook_data.status == "success" else 3  # 2=completed, 3=failed

        # # Find datasources by vault_unique_id in metadata
        # # We need to search in the datasource_metadata JSONB field
        # stmt = select(Datasource).where(
        #     Datasource.datasource_metadata['vault_unique_id'].astext.in_(vault_unique_ids)
        # )
        # result = await db.execute(stmt)
        # datasources = result.scalars().all()

        # processed_count = 0
        # failed_count = 0

        # for datasource in datasources:
        #     try:
        #         datasource.embedding_status = status
        #         if status == 3:  # Failed
        #             datasource.error_message = webhook_data.error_message or "Embedding processing failed"
        #         else:  # Success
        #             datasource.error_message = None
        #         processed_count += 1
        #     except Exception as e:
        #         print(f"Error updating datasource {datasource.id}: {str(e)}")
        #         failed_count += 1

        # await db.commit()

        # message = f"Successfully updated {processed_count} datasources"
        # if failed_count > 0:
        #     message += f", {failed_count} updates failed"

        # return MLWebhookResponse(
        #     message=message,
        #     processed_count=processed_count,
        #     failed_count=failed_count
        # )

        # Temporary response while status update is disabled
        return MLWebhookResponse(
            message="Webhook received but status update is temporarily disabled",
            processed_count=0,
            failed_count=0
        )

    except Exception as e:
        print(f"Error in ML webhook: {str(e)}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process webhook: {str(e)}"
        )
