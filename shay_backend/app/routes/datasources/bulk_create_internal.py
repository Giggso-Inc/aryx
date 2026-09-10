"""
Datasource POST /internal/bulk endpoint (create multiple thread-level
datasources in bulk, API-key authenticated — used by the email backend).
"""

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.schemas.datasource import DatasourceBulkCreateInternal, DatasourceBulkResponse

from ._bulk_embedding_dispatch import trigger_bulk_embeddings
from ._bulk_internal_auth import verify_internal_api_key
from ._bulk_internal_create_item import process_bulk_internal_item
from ._bulk_internal_skip import BulkItemSkipped
from ._bulk_item_failure import BulkItemFailure
from ._embedding_helpers import get_completed_embeddings_by_channel, get_completed_embeddings_by_thread

logger = logging.getLogger(__name__)

router = APIRouter()


def _thread_id_for_embedding(created_datasources) -> str:
    """Same-thread scope as the original: first embedding-required datasource's thread_id, if any."""
    for ds in created_datasources:
        if ds.get("is_embedding_required", False):
            meta = ds.get("datasource_metadata") or {}
            if isinstance(meta, dict) and meta.get("thread_id"):
                return meta.get("thread_id")
            break
    return None


async def _dispatch_internal_bulk_embeddings(created_datasources, db: AsyncSession) -> None:
    embedding_required_datasources = [ds for ds in created_datasources if ds.get("is_embedding_required", False)]
    if not embedding_required_datasources:
        return

    first_datasource = embedding_required_datasources[0]
    user_id = first_datasource.get("added_by")
    company_id = first_datasource.get("company_id")

    if not user_id or not company_id:
        logger.error(f"❌ Cannot proceed with embedding - missing user_id or company_id")
        logger.error(f"   user_id: {user_id}, company_id: {company_id}")
        return

    thread_id = _thread_id_for_embedding(created_datasources)
    if thread_id:
        logger.info(f"🧵 Thread-level embedding scope for internal/bulk: thread_id={thread_id}")
        embedded_ids_getter = lambda channel_id: get_completed_embeddings_by_thread(thread_id, db)
    else:
        embedded_ids_getter = lambda channel_id: get_completed_embeddings_by_channel(channel_id, db)

    jwt_token = settings.ML_API_KEY if settings.ML_API_KEY else None

    await trigger_bulk_embeddings(
        created_datasources,
        db,
        user_id=user_id,
        company_id=company_id,
        jwt_token=jwt_token,
        embedded_vault_unique_ids_for_channel=embedded_ids_getter,
        thread_id=thread_id,
        log_prefix=" (INTERNAL API)",
        mapping_log_suffix=" (Internal)",
    )


@router.post("/internal/bulk", response_model=DatasourceBulkResponse)
async def create_datasources_bulk_internal(
    bulk_data: DatasourceBulkCreateInternal,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
) -> DatasourceBulkResponse:
    """Create multiple datasources in bulk (internal API - thread-level, API key authentication)"""
    logger.info("=" * 80)
    logger.info("🚀 [INTERNAL-BULK] Starting internal bulk API call")
    logger.info(f"📦 Received {len(bulk_data.datasources)} datasource(s)")
    logger.info("=" * 80)

    try:
        verify_internal_api_key(request)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error verifying API key: {str(e)}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"API key verification failed: {str(e)}")

    created_datasources = []
    failed_datasources = []
    skipped_datasources = []  # Duplicates (same filename in same thread) - not failures

    try:
        for datasource_data in bulk_data.datasources:
            try:
                created_datasources.append(await process_bulk_internal_item(datasource_data, db))
            except BulkItemSkipped as skip:
                skipped_datasources.append({"name": skip.name, "reason": skip.reason, "message": skip.message})
            except BulkItemFailure as bulk_failure:
                failed_datasources.append({"name": bulk_failure.name, "error": bulk_failure.error})
            except Exception as e:
                logger.error(f"Error processing datasource in internal bulk API: {str(e)}", exc_info=True)
                failed_datasources.append({"name": datasource_data.name or "Unknown", "error": str(e)})

        await _dispatch_internal_bulk_embeddings(created_datasources, db)
    except Exception as e:
        logger.error(f"❌ [INTERNAL-BULK] Unhandled error in internal bulk API: {str(e)}", exc_info=True)
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return DatasourceBulkResponse(
            created_datasources=created_datasources if 'created_datasources' in locals() else [],
            failed_datasources=(failed_datasources if 'failed_datasources' in locals() else []) + [{"name": "Unknown", "error": f"Internal server error: {str(e)}"}]
        )

    logger.info(
        f"📊 [INTERNAL-BULK] Completed - Created: {len(created_datasources)}, "
        f"Failed: {len(failed_datasources)}, Skipped (duplicates): {len(skipped_datasources)}"
    )
    if failed_datasources:
        logger.warning(f"⚠️ [INTERNAL-BULK] Failed datasources: {failed_datasources}")
    if skipped_datasources:
        logger.info(f"⏭️ [INTERNAL-BULK] Skipped (duplicates in same thread): {skipped_datasources}")

    return DatasourceBulkResponse(
        created_datasources=created_datasources,
        failed_datasources=failed_datasources,
        total_created=len(created_datasources),
        total_failed=len(failed_datasources)
    )
