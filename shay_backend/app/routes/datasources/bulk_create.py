"""
Datasource POST /bulk endpoint (create multiple datasources in bulk).
"""

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.schemas.datasource import DatasourceBulkCreate, DatasourceBulkResponse

from ._bulk_create_item import process_bulk_create_item
from ._bulk_embedding_dispatch import trigger_bulk_embeddings
from ._bulk_item_failure import BulkItemFailure
from ._embedding_helpers import get_completed_embeddings_by_channel

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/bulk", response_model=DatasourceBulkResponse)
async def create_datasources_bulk(
    bulk_data: DatasourceBulkCreate,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
) -> DatasourceBulkResponse:
    """Create multiple datasources in bulk"""
    user = await get_current_user_required(request)

    created_datasources = []
    failed_datasources = []

    for datasource_data in bulk_data.datasources:
        try:
            created_datasources.append(await process_bulk_create_item(datasource_data, user, db))
        except BulkItemFailure as bulk_failure:
            failed_datasources.append({"name": bulk_failure.name, "error": bulk_failure.error})
        except Exception as e:
            failed_datasources.append({"name": datasource_data.name, "error": str(e)})

    # Extract JWT token from Authorization header
    auth_header = request.headers.get("Authorization")
    jwt_token = None
    if auth_header and auth_header.startswith("Bearer "):
        jwt_token = auth_header.split(" ")[1]

    await trigger_bulk_embeddings(
        created_datasources,
        db,
        user_id=str(user.id),
        company_id=str(user.company_id),
        jwt_token=jwt_token,
        embedded_vault_unique_ids_for_channel=lambda channel_id: get_completed_embeddings_by_channel(channel_id, db),
    )

    logger.info(f"📊 [INTERNAL-BULK] Completed - Created: {len(created_datasources)}, Failed: {len(failed_datasources)}")
    if failed_datasources:
        logger.warning(f"⚠️ [INTERNAL-BULK] Failed datasources: {failed_datasources}")

    return DatasourceBulkResponse(
        created_datasources=created_datasources,
        failed_datasources=failed_datasources,
        total_created=len(created_datasources),
        total_failed=len(failed_datasources)
    )
