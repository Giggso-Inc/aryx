"""
Datasource embedding status/webhook/regenerate endpoints.
"""

import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import String, and_, desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.expression import literal

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.channel import Channel
from app.models.datasource import Datasource
from app.models.giggso_vault import GiggsoVault
from app.schemas.datasource import (
    EmbeddingStatusResponse,
    MLWebhookRequest,
    MLWebhookResponse,
    RegenerateEmbeddingResponse,
)
from app.services.ml_service import extract_table_names_from_datasources, ml_service
from app.services.socket_client_service import get_socket_service
from app.utils.channel_access import check_channel_access, check_channel_access_by_thread

from ._shared import (
    get_completed_embeddings_by_channel,
    get_openai_vault_token_for_company,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/embedding-status/{channel_id}", response_model=EmbeddingStatusResponse)
async def get_embedding_status_by_channel(
    channel_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    thread_id: Optional[str] = Query(
        None,
        description="Filter by thread ID. When set, returns embedding status only for thread-level datasources (e.g. email attachments in that thread). When omitted, returns channel-level datasources only."
    )
) -> EmbeddingStatusResponse:
    """Get embedding status for datasources in a channel. Pass thread_id to get status for thread-level datasources (email attachments) only."""
    user = await get_current_user_required(request)
    
    # Check channel access - user must be super admin or channel member
    await check_channel_access(db, user, channel_id)
    
    # Get channel
    stmt = select(Channel).where(Channel.id == channel_id)
    result = await db.execute(stmt)
    channel = result.scalar_one_or_none()
    
    if not channel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Channel not found"
        )
    
    # When thread_id is passed: return only thread-level datasources for that thread (e.g. email attachments)
    # Same behaviour as GET /datasources/?channel_id=...&thread_id=...
    if thread_id:
        try:
            thread_uuid = uuid.UUID(thread_id)
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid thread_id format: {thread_id}"
            )
        await check_channel_access_by_thread(db, user, thread_id)
        # For thread-level datasources: get all datasources for the thread, then filter to keep only latest per filename
        stmt = select(Datasource).where(
            and_(
                Datasource.channel_id == channel_id,
                Datasource.datasource_metadata.isnot(None),
                Datasource.datasource_metadata.op("?")(literal("thread_id", type_=String())),
                Datasource.datasource_metadata.op("->>")(literal("thread_id", type_=String())) == literal(str(thread_uuid), type_=String())
            )
        ).order_by(desc(Datasource.created_at))  # Order by created_at DESC to get latest first
        result = await db.execute(stmt)
        all_datasources = result.scalars().all()
        
        # Group by filename and keep only the latest one (first in DESC order)
        seen_filenames = {}
        datasources = []
        for ds in all_datasources:
            filename_key = ds.filename or ds.name or "unknown"  # Use filename as key, fallback to name
            if filename_key not in seen_filenames:
                seen_filenames[filename_key] = True
                datasources.append(ds)  # Keep only the first (latest) occurrence
    else:
        # Get only channel-level datasources (exclude thread-level e.g. email attachments)
        # Thread-level datasources have datasource_metadata.thread_id set
        stmt = select(Datasource).where(
            and_(
                Datasource.channel_id == channel_id,
                or_(
                    Datasource.datasource_metadata.is_(None),
                    ~Datasource.datasource_metadata.op("?")(literal("thread_id", type_=String()))
                )
            )
        )
        result = await db.execute(stmt)
        datasources = result.scalars().all()

    # Categorize datasources by embedding status
    total_datasources = len(datasources)
    embedding_required = 0
    in_progress = 0
    completed = 0
    failed = 0
    not_required = 0
    
    datasource_list = []
    
    for ds in datasources:
        if ds.is_embedding_required:
            embedding_required += 1
        
        if ds.embedding_status == 0:
            not_required += 1
        elif ds.embedding_status == 1:
            in_progress += 1
        elif ds.embedding_status == 2:
            completed += 1
        elif ds.embedding_status == 3:
            failed += 1
        
        datasource_list.append({
            "id": str(ds.id),
            "name": ds.name,
            "filename": ds.filename,
            "is_embedding_required": ds.is_embedding_required,
            "embedding_status": ds.embedding_status,
            "error_message": ds.error_message,
            "created_at": ds.created_at,
            "updated_at": ds.updated_at
        })
    
    return EmbeddingStatusResponse(
        channel_id=channel_id,
        total_datasources=total_datasources,
        embedding_required=embedding_required,
        in_progress=in_progress,
        completed=completed,
        failed=failed,
        not_required=not_required,
        datasources=datasource_list
    )

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
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Datasource not found"
            )
        
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
        # Call ML service directly
        try:
            table_names = extract_table_names_from_datasources([datasource]) if table_name is None else None
            result = await ml_service.request_embedding_processing(
                vault_unique_ids=[vault_record.vault_unique_id],
                user_id=current_user_id,
                company_id=current_company_id,
                channel_id=str(datasource.channel_id),
                embedded_vault_unique_ids=embedded_vault_unique_ids,
                jwt_token=jwt_token,
                embedd_type=embedd_type,
                table_name=table_name,
                table_names=table_names,
                openai_vault_token=openai_vault_token
            )
            
            # Emit socket event based on ML API response
            socket_service = get_socket_service()
            if socket_service.is_socket_connected():
                # Determine status based on ML API response
                ml_status = 2 if result.get("success") else 3  # 2 = success, 3 = failure
                
                socket_event_data = {
                    "type": 16,
                    "data": {
                        "channelId": str(datasource.channel_id),
                        "status": ml_status,
                        "datasourceId": datasource_id
                    }
                }
                
                try:
                    await socket_service.emit("shay_realtime", socket_event_data)
                    logger.info(f"✅ Emitted socket event for datasource {datasource_id}: status={ml_status}")
                except Exception as socket_error:
                    logger.error(f"❌ Failed to emit socket event for datasource {datasource_id}: {socket_error}")
            
            if result.get("success"):
                logger.info("✅ ML API call successful - embedding processing initiated")
            else:
                logger.error(f"❌ ML API call failed: {result.get('message', 'Unknown error')}")
                # TODO: Status update to failed is handled by ML team via webhook
                # datasource.embedding_status = 3  # 3 = failed
                # await db.commit()
                
        except Exception as e:
            logger.error(f"❌ Error calling ML API: {e}")
            
            # Emit socket event for failure
            socket_service = get_socket_service()
            if socket_service.is_socket_connected():
                socket_event_data = {
                    "type": 16,
                    "data": {
                        "channelId": str(datasource.channel_id),
                        "status": 3,  # 3 = failure
                        "datasourceId": datasource_id
                    }
                }
                
                try:
                    await socket_service.emit("shay_realtime", socket_event_data)
                    logger.info(f"✅ Emitted socket event for datasource {datasource_id}: status=3 (failure)")
                except Exception as socket_error:
                    logger.error(f"❌ Failed to emit socket event for datasource {datasource_id}: {socket_error}")
            
            # TODO: Status update to failed is handled by ML team via webhook
            # datasource.embedding_status = 3  # 3 = failed
            # await db.commit()
        
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
