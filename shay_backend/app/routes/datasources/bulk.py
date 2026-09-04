"""
Datasource bulk-create endpoints (public + internal).
"""

import os
import uuid
from urllib.parse import unquote, urlparse

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy import String, and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.expression import literal

from app.core.config import settings
from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.channel import Channel
from app.models.datasource import Datasource
from app.models.giggso_vault import GiggsoVault
from app.models.message import Thread
from app.models.user import User
from app.schemas.datasource import (
    DatasourceBulkCreate,
    DatasourceBulkCreateInternal,
    DatasourceBulkResponse,
)
from app.services.ml_service import extract_table_names_from_datasources, ml_service
from app.services.socket_client_service import get_socket_service
from app.services.vault_data_builder import enhance_datasource_metadata

from ._shared import (
    _aryx_ingestion_status_for,
    clean_metadata,
    generate_app_filename,
    generate_datasource_metadata,
    get_completed_embeddings_by_channel,
    get_completed_embeddings_by_thread,
    get_openai_vault_token_for_company,
    handle_vault_integration,
    sanitize_datasource_metadata,
)

import logging

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
            # Get channel
            stmt = select(Channel).where(Channel.id == datasource_data.channel_id)
            result = await db.execute(stmt)
            channel = result.scalar_one_or_none()
            
            if not channel:
                failed_datasources.append({
                    "name": datasource_data.name,
                    "error": "Channel not found"
                })
                continue
            
            # Check permissions
            if not channel.is_accessible_by_user(user.company_id, user.role):
                failed_datasources.append({
                    "name": datasource_data.name,
                    "error": "Access denied to channel"
                })
                continue
            
            # Check for duplicate datasource in the same channel
            existing_datasource_stmt = select(Datasource).where(
                and_(
                    Datasource.name == datasource_data.name,
                    Datasource.channel_id == datasource_data.channel_id
                )
            )
            existing_datasource_result = await db.execute(existing_datasource_stmt)
            existing_datasource = existing_datasource_result.scalars().first()
            
            if existing_datasource:
                failed_datasources.append({
                    "name": datasource_data.name,
                    "error": f"Datasource with name '{datasource_data.name}' already exists in this channel"
                })
                continue
            
            # Validate storage type specific requirements
            if datasource_data.storage_type == "cloud" and not datasource_data.provider:
                failed_datasources.append({
                    "name": datasource_data.name,
                    "error": "Provider is required for cloud storage type"
                })
                continue
            
            if datasource_data.storage_type == "app" and not datasource_data.app_type:
                failed_datasources.append({
                    "name": datasource_data.name,
                    "error": "App type is required for app storage type"
                })
                continue
            # Handle app_provider mapping for app storage
            if datasource_data.storage_type == "app":
                # Map app_provider to provider for app storage
                if datasource_data.app_provider and not datasource_data.provider:
                    datasource_data.provider = datasource_data.app_provider
                elif not datasource_data.app_provider and not datasource_data.provider:
                    failed_datasources.append({
                        "name": datasource_data.name,
                        "error": "app_provider is required for app storage type"
                    })
                    continue

            # Auto-generate name from filename if not provided
            datasource_name = datasource_data.name
            if not datasource_name:
                # Get filename (either provided or extract from URL)
                filename = datasource_data.filename
                if not filename and datasource_data.file_url:
                    # Extract filename from URL
                    filename = os.path.basename(datasource_data.file_url.split('?')[0])  # Remove query params
                    if not filename:
                        filename = "cloud_file"  # Fallback name
                
                if filename:
                    # Remove extension and replace underscores/hyphens with spaces
                    base_filename = os.path.splitext(filename)[0]
                    datasource_name = base_filename.replace('_', ' ').replace('-', ' ').title()
                else:
                    # Handle app storage type with no filename
                    if datasource_data.storage_type == "app":
                        app_type = getattr(datasource_data, 'app_type', 'unknown')
                        datasource_name = f"{app_type.title()} Datasource"
                    else:
                        datasource_name = "Cloud Datasource"  # Default name
            filename = datasource_data.filename
            if not filename and datasource_data.file_url:
                # Extract filename from URL
                filename = os.path.basename(datasource_data.file_url.split('?')[0])  # Remove query params
                if not filename:
                    filename = "cloud_file"  # Fallback name
            
            # Handle app storage type with no filename - generate meaningful filename first
            if not filename and datasource_data.storage_type == "app":
                # Try to create a meaningful filename from connection_settings
                filename = generate_app_filename(datasource_data)
            # Generate metadata structure
            metadata = generate_datasource_metadata(
                filename=filename or "app_file",
                storage_type=datasource_data.storage_type,
                channel_id=datasource_data.channel_id,
                workspace_id=str(channel.workspace_id),
                user_id=str(user.id),
                file_size=datasource_data.file_size or 0,  # Fallback for app storage
                file_type=datasource_data.file_type or "application/octet-stream",  # Fallback for app storage
                provider=datasource_data.provider,
                app_type=datasource_data.app_type,
                log_type=datasource_data.log_type,
                config=datasource_data.config.dict() if datasource_data.config else None,
                file_url=datasource_data.file_url,
                is_embedding_required=datasource_data.is_embedding_required or False
            )
            
            # Get filename (either provided or extract from URL)
            filename = datasource_data.filename
            if not filename and datasource_data.file_url:
                # Extract filename from URL
                filename = os.path.basename(datasource_data.file_url.split('?')[0])  # Remove query params
                if not filename:
                    filename = "cloud_file"  # Fallback name
                                       
            # Handle app storage type with no filename
            if not filename and datasource_data.storage_type == "app":
                # Try to create a meaningful filename from connection_settings
                filename = generate_app_filename(datasource_data)
            # Clean the metadata to remove null, empty, and default values
            cleaned_metadata = clean_metadata(metadata)
            
            # Enhance metadata with vault-specific fields AFTER cleaning
            from app.services.vault_data_builder import enhance_datasource_metadata
            
            enhanced_metadata = await enhance_datasource_metadata(
                existing_metadata=cleaned_metadata,
                storage_type=datasource_data.storage_type,
                provider=datasource_data.provider,
                config=datasource_data.config.dict() if datasource_data.config else None,
                app_type=getattr(datasource_data, 'app_type', None),
                db=db,
                channel_id=datasource_data.channel_id,
                location=getattr(datasource_data, 'location', None),
                accessToken=getattr(datasource_data, 'accessToken', None)
            )
            
            # Handle vault integration for datasource metadata
            vault_unique_id = None
            if enhanced_metadata:
                # Vault integration is REQUIRED for ALL datasource types to ensure data security
                # This includes both cloud datasources (with sensitive credentials) and local files
                vault_required = True
                
                try:
                    vault_result = await handle_vault_integration(
                        datasource_metadata=enhanced_metadata,
                        user_id=str(user.id),
                        company_id=str(channel.company_id),
                        db=db,
                        required=vault_required
                    )
                    vault_unique_id = vault_result["vault_unique_id"] if vault_result else None
                    giggso_vault_id = vault_result["giggso_vault_id"] if vault_result else None
                    
                    # If vault integration failed, we cannot proceed with datasource creation
                    if not vault_unique_id:
                        failed_datasources.append({
                            "name": datasource_data.name,
                            "error": "Vault integration failed. Cannot create datasource without secure storage."
                        })
                        continue
                        
                except HTTPException as e:
                    # Vault integration failed - add to failed datasources
                    failed_datasources.append({
                        "name": datasource_data.name,
                        "error": f"Vault integration failed: {e.detail}"
                    })
                    continue
                except Exception as e:
                    # For unexpected errors, log and fail
                    print(f"Unexpected error during vault integration: {str(e)}")
                    failed_datasources.append({
                        "name": datasource_data.name,
                        "error": "Failed to integrate with vault service"
                    })
                    continue
            
            # Store enhanced metadata directly in database (with vault integration for backup)
            final_metadata = enhanced_metadata.copy()
            if vault_unique_id:
                final_metadata["vault_unique_id"] = str(vault_unique_id)
            
            # Create datasource
            datasource = Datasource(
                id=str(uuid.uuid4()),
                name=datasource_name,
                filename=filename,
                storage_type=datasource_data.storage_type,
                provider=datasource_data.provider,
                app_type=datasource_data.app_type,
                log_type=datasource_data.log_type,
                config=datasource_data.config.dict() if datasource_data.config else None,
                datasource_metadata=final_metadata,
                giggso_vault_id=giggso_vault_id,  # Store vault ID in dedicated column
                file_size=datasource_data.file_size or 0,  # Fallback for app storage
                file_type=datasource_data.file_type or "application/octet-stream",  # Fallback for app storage
                file_url=datasource_data.file_url,
                channel_id=datasource_data.channel_id,
                added_by=user.id,
                is_embedding_required=datasource_data.is_embedding_required or False,
                embedding_status=1 if (datasource_data.is_embedding_required or False) else 0
            )
            
            db.add(datasource)
            await db.commit()
            await db.refresh(datasource)
            
            created_datasources.append({
                "id": str(datasource.id),
                "name": datasource.name,
                "filename": datasource.filename,
                "storage_type": datasource.storage_type,
                "provider": datasource.provider,
                "app_type": datasource.app_type,
                "config": datasource.config,
                "datasource_metadata": sanitize_datasource_metadata(datasource.datasource_metadata),
                "giggso_vault_id": str(datasource.giggso_vault_id) if datasource.giggso_vault_id else None,
                "file_size": datasource.file_size,
                "file_type": datasource.file_type,
                "file_url": datasource.file_url,
                "channel_id": str(datasource.channel_id),
                "workspace_id": str(channel.workspace_id),
                "company_id": str(channel.company_id),
                "added_by": str(datasource.added_by),
                "is_active": datasource.is_active,
                "is_connected": datasource.is_connected,
                "is_processed": datasource.is_processed,
                "processing_status": datasource.processing_status,
                "error_message": datasource.error_message,
                "last_processed_at": datasource.last_processed_at,
                "processing_time": datasource.processing_time,
                "record_count": datasource.record_count,
                "is_embedding_required": datasource.is_embedding_required,
                "embedding_status": datasource.embedding_status,
                "created_at": datasource.created_at,
                "updated_at": datasource.updated_at,
                # Additive: None for every datasource without an aryx.discovery_id
                # in its metadata — existing (non-Aryx) callers see no change.
                "aryx_ingestion_status": await _aryx_ingestion_status_for(datasource.datasource_metadata),
            })

        except Exception as e:
            failed_datasources.append({
                "name": datasource_data.name,
                "error": str(e)
            })

    # Check if any datasources require embedding processing
    embedding_required_datasources = [
        ds for ds in created_datasources
        if ds.get("is_embedding_required", False)
    ]
    
    if embedding_required_datasources:
        # Extract giggso_vault_ids and get corresponding vault_unique_ids
        giggso_vault_ids = []
        for ds in embedding_required_datasources:
            if ds.get("giggso_vault_id"):
                giggso_vault_ids.append(ds["giggso_vault_id"])
        
        vault_unique_ids = []  # Initialize vault_unique_ids outside the if block
        vault_records = []  # Initialize vault_records outside the if block
        
        if giggso_vault_ids:
            # Query gg_vault table to get vault_unique_ids
            stmt = select(GiggsoVault).where(GiggsoVault.giggso_vault_id.in_(giggso_vault_ids))
            result = await db.execute(stmt)
            vault_records = result.scalars().all()
            
            # Extract vault_unique_ids
            vault_unique_ids = [record.vault_unique_id for record in vault_records if record.vault_unique_id]
            
            logger.info("=" * 80)
            logger.info("🔍 VAULT ID CONVERSION")
            logger.info("=" * 80)
            logger.info(f"📊 Found {len(embedding_required_datasources)} datasources requiring embedding")
            logger.info(f"🔑 giggso_vault_ids: {giggso_vault_ids}")
            logger.info(f"📦 vault_unique_ids: {vault_unique_ids}")
            logger.info("=" * 80)
        
        if vault_unique_ids:
            # Get channel_id from the first datasource that requires embedding
            first_datasource = embedding_required_datasources[0]
            channel_id = first_datasource.get("channel_id")
            
            # Classify each datasource by embedd_type and group them
            from app.services.ml_service import get_embedd_type_from_file_type
            
            # Create a mapping: datasource -> embedd_type -> giggso_vault_id -> vault_unique_id
            # First, create a mapping from giggso_vault_id to vault_unique_id
            vault_id_mapping = {}
            for ds in embedding_required_datasources:
                giggso_vault_id = ds.get("giggso_vault_id")
                if giggso_vault_id:
                    # Find corresponding vault_unique_id
                    for record in vault_records:
                        # Convert both to strings for comparison to handle UUID vs string mismatches
                        if str(record.giggso_vault_id) == str(giggso_vault_id):
                            vault_id_mapping[str(giggso_vault_id)] = record.vault_unique_id
                            break
            
            logger.debug(f"🔍 Vault ID Mapping created: {len(vault_id_mapping)} mappings")
            logger.debug(f"   Mapping keys: {list(vault_id_mapping.keys())}")
            logger.debug(f"   Vault records count: {len(vault_records)}")
            logger.debug(f"   Embedding required datasources count: {len(embedding_required_datasources)}")
            
            # Group datasources by embedd_type
            textual_datasources = []
            tabular_datasources = []
            
            for ds in embedding_required_datasources:
                # Determine embedd_type for this datasource
                embedd_type = get_embedd_type_from_file_type(
                    file_type=ds.get("file_type"),
                    storage_type=ds.get("storage_type"),
                    provider=ds.get("provider")
                )
                
                # Extract base type (remove provider suffix if any)
                base_type = embedd_type.split("_")[0]
                
                # Group by base type
                if base_type == "tabular":
                    tabular_datasources.append({
                        "datasource": ds,
                        "giggso_vault_id": ds.get("giggso_vault_id"),
                        "embedd_type": embedd_type
                    })
                else:
                    # Default to textual for unknown types or textual files
                    textual_datasources.append({
                        "datasource": ds,
                        "giggso_vault_id": ds.get("giggso_vault_id"),
                        "embedd_type": embedd_type
                    })
            
            logger.info("=" * 80)
            logger.info("📊 FILE CLASSIFICATION FOR BULK EMBEDDING")
            logger.info("=" * 80)
            logger.info(f"📄 Textual files: {len(textual_datasources)}")
            logger.info(f"📊 Tabular files: {len(tabular_datasources)}")
            logger.info("=" * 80)
            
            # Get completed embeddings for this channel
            embedded_vault_unique_ids = await get_completed_embeddings_by_channel(channel_id, db)

            # Extract JWT token from Authorization header
            auth_header = request.headers.get("Authorization")
            jwt_token = None
            if auth_header and auth_header.startswith("Bearer "):
                jwt_token = auth_header.split(" ")[1]
            
            # Fetch OpenAI vault token (gpt_token) for company to send to ML API
            openai_vault_token = await get_openai_vault_token_for_company(db, str(user.company_id))
            
            # Process textual files group
            if textual_datasources:
                textual_vault_unique_ids = [
                    vault_id_mapping[str(ds["giggso_vault_id"])]
                    for ds in textual_datasources
                    if ds["giggso_vault_id"] and str(ds["giggso_vault_id"]) in vault_id_mapping
                ]
                
                logger.debug(f"📄 Textual vault_unique_ids: {textual_vault_unique_ids} (from {len(textual_datasources)} textual datasources)")
                
                if textual_vault_unique_ids:
                    textual_ds_list = [ds["datasource"] for ds in textual_datasources]
                    
                    # Extract table_name from first textual datasource metadata that has it
                    table_name = None
                    for ds in textual_datasources:
                        metadata = ds["datasource"].get("datasource_metadata")
                        if metadata and isinstance(metadata, dict):
                            table_name = metadata.get("tableName")
                            if table_name:
                                break
                    
                    try:
                        table_names = extract_table_names_from_datasources(textual_ds_list) if len(textual_ds_list) > 1 else None
                        logger.info(f"🚀 Calling ML API for {len(textual_vault_unique_ids)} textual file(s) with embedd_type='textual'")
                        
                        result = await ml_service.request_embedding_processing(
                            vault_unique_ids=textual_vault_unique_ids,
                            user_id=str(user.id),
                            company_id=str(user.company_id),
                            channel_id=channel_id,
                            embedded_vault_unique_ids=embedded_vault_unique_ids,
                            jwt_token=jwt_token,
                            embedd_type="textual",
                            table_name=table_name,
                            table_names=table_names,
                            openai_vault_token=openai_vault_token
                        )
                        
                        # Emit socket event based on ML API response
                        socket_service = get_socket_service()
                        if socket_service.is_socket_connected():
                            ml_status = 2 if result.get("success") else 3  # 2 = success, 3 = failure
                            
                            # Emit socket event for each textual datasource
                            for ds in textual_datasources:
                                datasource_id = ds["datasource"].get("id")
                                if datasource_id:
                                    socket_event_data = {
                                        "type": 16,
                                        "data": {
                                            "channelId": channel_id,
                                            "status": ml_status,
                                            "datasourceId": datasource_id
                                        }
                                    }
                                    
                                    try:
                                        await socket_service.emit("shay_realtime", socket_event_data)
                                        logger.info(f"✅ Emitted socket event for textual datasource {datasource_id}: status={ml_status}")
                                    except Exception as socket_error:
                                        logger.error(f"❌ Failed to emit socket event for datasource {datasource_id}: {socket_error}")
                        
                        if result.get("success"):
                            logger.info(f"✅ ML API call successful for {len(textual_vault_unique_ids)} textual file(s)")
                        else:
                            logger.error(f"❌ ML API call failed for textual files: {result.get('message', 'Unknown error')}")
                            
                    except Exception as e:
                        logger.error(f"❌ Error calling ML API for textual files: {e}")
                        
                        # Emit socket event for failure
                        socket_service = get_socket_service()
                        if socket_service.is_socket_connected():
                            for ds in textual_datasources:
                                datasource_id = ds["datasource"].get("id")
                                if datasource_id:
                                    try:
                                        await socket_service.emit("shay_realtime", {
                                            "type": 16,
                                            "data": {
                                                "channelId": channel_id,
                                                "status": 3,  # failure
                                                "datasourceId": datasource_id
                                            }
                                        })
                                    except Exception:
                                        pass
            
            # Process tabular files group
            if tabular_datasources:
                tabular_vault_unique_ids = [
                    vault_id_mapping[str(ds["giggso_vault_id"])]
                    for ds in tabular_datasources
                    if ds["giggso_vault_id"] and str(ds["giggso_vault_id"]) in vault_id_mapping
                ]
                
                logger.debug(f"📊 Tabular vault_unique_ids: {tabular_vault_unique_ids} (from {len(tabular_datasources)} tabular datasources)")
                
                if tabular_vault_unique_ids:
                    tabular_ds_list = [ds["datasource"] for ds in tabular_datasources]
                    
                    # Extract table_name from first tabular datasource metadata that has it
                    table_name = None
                    for ds in tabular_datasources:
                        metadata = ds["datasource"].get("datasource_metadata")
                        if metadata and isinstance(metadata, dict):
                            table_name = metadata.get("tableName")
                            if table_name:
                                break
                    
                    try:
                        table_names = extract_table_names_from_datasources(tabular_ds_list) if len(tabular_ds_list) > 1 else None
                        logger.info(f"🚀 Calling ML API for {len(tabular_vault_unique_ids)} tabular file(s) with embedd_type='tabular'")
                        
                        result = await ml_service.request_embedding_processing(
                            vault_unique_ids=tabular_vault_unique_ids,
                            user_id=str(user.id),
                            company_id=str(user.company_id),
                            channel_id=channel_id,
                            embedded_vault_unique_ids=embedded_vault_unique_ids,
                            jwt_token=jwt_token,
                            embedd_type="tabular",
                            table_name=table_name,
                            table_names=table_names,
                            openai_vault_token=openai_vault_token
                        )
                        
                        # Emit socket event based on ML API response
                        socket_service = get_socket_service()
                        if socket_service.is_socket_connected():
                            ml_status = 2 if result.get("success") else 3  # 2 = success, 3 = failure
                            
                            # Emit socket event for each tabular datasource
                            for ds in tabular_datasources:
                                datasource_id = ds["datasource"].get("id")
                                if datasource_id:
                                    socket_event_data = {
                                        "type": 16,
                                        "data": {
                                            "channelId": channel_id,
                                            "status": ml_status,
                                            "datasourceId": datasource_id
                                        }
                                    }
                                    
                                    try:
                                        await socket_service.emit("shay_realtime", socket_event_data)
                                        logger.info(f"✅ Emitted socket event for tabular datasource {datasource_id}: status={ml_status}")
                                    except Exception as socket_error:
                                        logger.error(f"❌ Failed to emit socket event for datasource {datasource_id}: {socket_error}")
                        
                        if result.get("success"):
                            logger.info(f"✅ ML API call successful for {len(tabular_vault_unique_ids)} tabular file(s)")
                        else:
                            logger.error(f"❌ ML API call failed for tabular files: {result.get('message', 'Unknown error')}")
                            
                    except Exception as e:
                        logger.error(f"❌ Error calling ML API for tabular files: {e}")
                        
                        # Emit socket event for failure
                        socket_service = get_socket_service()
                        if socket_service.is_socket_connected():
                            for ds in tabular_datasources:
                                datasource_id = ds["datasource"].get("id")
                                if datasource_id:
                                    try:
                                        await socket_service.emit("shay_realtime", {
                                            "type": 16,
                                            "data": {
                                                "channelId": channel_id,
                                                "status": 3,  # failure
                                                "datasourceId": datasource_id
                                            }
                                        })
                                    except Exception:
                                        pass
    
    logger.info(f"📊 [INTERNAL-BULK] Completed - Created: {len(created_datasources)}, Failed: {len(failed_datasources)}")
    if failed_datasources:
        logger.warning(f"⚠️ [INTERNAL-BULK] Failed datasources: {failed_datasources}")
    
    return DatasourceBulkResponse(
        created_datasources=created_datasources,
        failed_datasources=failed_datasources,
        total_created=len(created_datasources),
        total_failed=len(failed_datasources)
    )

def verify_internal_api_key(request: Request) -> None:
    """Verify internal API key from request headers"""
    api_key = request.headers.get("X-API-Key") or request.headers.get("Authorization", "").replace("Bearer ", "")
    
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key is required. Provide X-API-Key header or Bearer token."
        )
    
    expected_api_key = settings.ML_API_KEY
    if not expected_api_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="API key not configured. Set ML_API_KEY environment variable."
        )
    
    if api_key != expected_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key"
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
        # Verify API key
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
                # Convert thread_id to UUID
                try:
                    thread_uuid = uuid.UUID(datasource_data.thread_id)
                except (ValueError, TypeError) as e:
                    failed_datasources.append({"name": datasource_data.name or "Unknown", "error": f"Invalid thread_id format: {datasource_data.thread_id}"})
                    continue

                # Get thread
                thread_stmt = select(Thread).where(Thread.id == thread_uuid)
                thread_result = await db.execute(thread_stmt)
                thread = thread_result.scalar_one_or_none()

                if not thread:
                    failed_datasources.append({"name": datasource_data.name or "Unknown", "error": "Thread not found"})
                    continue

                # Get channel from thread
                channel_stmt = select(Channel).where(Channel.id == thread.channel_id)
                channel_result = await db.execute(channel_stmt)
                channel = channel_result.scalar_one_or_none()

                if not channel:
                    failed_datasources.append({"name": datasource_data.name or "Unknown", "error": "Channel not found for thread"})
                    continue

                # Get user from channel's connected email account (AppAccount)
                # For email attachments, use the user who connected the email account to the channel
                user = None
                try:
                    from app.models.app_account import AppAccount
                    # Get the active email AppAccount for this channel
                    app_account_stmt = select(AppAccount).where(
                        and_(
                            AppAccount.channel_id == thread.channel_id,
                            AppAccount.api_key == "email",
                            AppAccount.is_active == True
                        )
                    ).order_by(AppAccount.created_at.desc()).limit(1)
                    app_account_result = await db.execute(app_account_stmt)
                    app_account = app_account_result.scalar_one_or_none()
                    
                    if app_account and app_account.connected_by:
                        # Use the user who connected the email account
                        user_stmt = select(User).where(User.id == app_account.connected_by)
                        user_result = await db.execute(user_stmt)
                        user = user_result.scalar_one_or_none()
                        logger.info(f"✅ Using connected email account user for attachment: user_id={app_account.connected_by}")
                except Exception as e:
                    logger.warning(f"Could not get user from AppAccount: {str(e)}")
                
                # Fallback: Get first active user from channel's company if no AppAccount found
                if not user:
                    user_stmt = select(User).where(and_(User.company_id == channel.company_id, User.is_active == True)).limit(1)
                    user_result = await db.execute(user_stmt)
                    user = user_result.scalar_one_or_none()
                    logger.info(f"⚠️ Using fallback: first active user from company for attachment")

                if not user:
                    failed_datasources.append({"name": datasource_data.name or "Unknown", "error": "No active user found for channel's company"})
                    continue

                # Resolve filename early (needed for duplicate check when name not provided)
                filename = datasource_data.filename
                if not filename and datasource_data.file_url:
                    filename = os.path.basename(datasource_data.file_url.split('?')[0])  # Remove query params
                    if not filename:
                        filename = "cloud_file"  # Fallback name

                # Skip .ics attachments in internal/bulk API (not supported)
                # Check both explicit filename and file_url path so we never process .ics from either source
                fn_lower = (filename or "").strip().lower()
                is_ics = fn_lower.endswith(".ics")
                if not is_ics and datasource_data.file_url:
                    path_part = datasource_data.file_url.split("?")[0].rstrip("/")
                    if path_part:
                        last_segment = path_part.split("/")[-1]
                        is_ics = last_segment.lower().endswith(".ics")
                if is_ics:
                    skip_name = datasource_data.name or filename or "Unknown"
                    skipped_datasources.append({
                        "name": skip_name,
                        "reason": "unsupported_extension",
                        "message": "Attachments with .ics extension are not supported in bulk API",
                    })
                    continue  # Do not create datasource for .ics attachments

                # Auto-generate name from filename if not provided (same logic used when creating)
                datasource_name = datasource_data.name
                if not datasource_name:
                    if filename:
                        base_filename = os.path.splitext(filename)[0]
                        datasource_name = base_filename.replace('_', ' ').replace('-', ' ').title()
                    else:
                        if getattr(datasource_data, 'storage_type', None) == "app":
                            app_type = getattr(datasource_data, 'app_type', 'unknown')
                            datasource_name = f"{app_type.title()} Datasource"
                        else:
                            datasource_name = "Cloud Datasource"  # Default name

                # Check for duplicate ONLY within the same thread: use (filename, thread_id) for precision.
                # Same filename in SAME thread = duplicate (skip). Same filename in DIFFERENT thread = process.
                # Filename is the actual file identity; name can collide across different files (e.g. Report.pdf vs Report.docx).
                filename_for_check = (filename or "").strip() or None
                duplicate_check_key = filename_for_check if filename_for_check else datasource_name
                if duplicate_check_key:
                    # Match by filename when available (more precise); fallback to name for app-type datasources
                    if filename_for_check:
                        duplicate_stmt = select(Datasource).where(
                            and_(
                                Datasource.filename == filename_for_check,
                                Datasource.channel_id == thread.channel_id,
                                Datasource.datasource_metadata.isnot(None),
                                Datasource.datasource_metadata.op("?")(literal("thread_id", type_=String())),
                                Datasource.datasource_metadata.op("->>")(literal("thread_id", type_=String())) == literal(str(thread_uuid), type_=String())
                            )
                        ).limit(1)
                    else:
                        duplicate_stmt = select(Datasource).where(
                            and_(
                                Datasource.name == datasource_name,
                                Datasource.channel_id == thread.channel_id,
                                Datasource.datasource_metadata.isnot(None),
                                Datasource.datasource_metadata.op("?")(literal("thread_id", type_=String())),
                                Datasource.datasource_metadata.op("->>")(literal("thread_id", type_=String())) == literal(str(thread_uuid), type_=String())
                            )
                        ).limit(1)
                    duplicate_result = await db.execute(duplicate_stmt)
                    existing_datasource = duplicate_result.scalar_one_or_none()

                    if existing_datasource:
                        # Duplicate (same file in same thread) - skip, do not count as failed
                        logger.info(
                            f"⏭️ Skipping duplicate datasource: {datasource_name} (filename={filename_for_check or 'N/A'} "
                            f"already exists in thread {thread_uuid})"
                        )
                        skipped_datasources.append({
                            "name": datasource_name,
                            "reason": "already_exists",
                            "message": f"Datasource '{datasource_name}' already exists in this thread (skipped)"
                        })
                        continue
                
                # Get filename (either provided or extract from URL)
                filename = datasource_data.filename
                if not filename and datasource_data.file_url:
                    # Extract filename from URL
                    filename = os.path.basename(datasource_data.file_url.split('?')[0])  # Remove query params
                    if not filename:
                        filename = "cloud_file"  # Fallback name
                
                # Handle app storage type with no filename - generate meaningful filename first
                if not filename and datasource_data.storage_type == "app":
                    # Try to create a meaningful filename from connection_settings
                    filename = generate_app_filename(datasource_data)
                
                # Generate metadata structure (use thread's channel_id)
                metadata = generate_datasource_metadata(
                    filename=filename or "app_file",
                    storage_type=datasource_data.storage_type,
                    channel_id=str(thread.channel_id),
                    workspace_id=str(thread.workspace_id),
                    user_id=str(user.id),
                    file_size=datasource_data.file_size or 0,  # Fallback for app storage
                    file_type=datasource_data.file_type or "application/octet-stream",  # Fallback for app storage
                    provider=datasource_data.provider,
                    app_type=datasource_data.app_type,
                    log_type=datasource_data.log_type,
                    config=datasource_data.config.dict() if datasource_data.config else None,
                    file_url=datasource_data.file_url,
                    is_embedding_required=datasource_data.is_embedding_required or False
                )
                
                # Add thread_id to metadata for thread-level association
                metadata["thread_id"] = str(thread_uuid)
                # Ensure company_id is in metadata for embedding processing
                if "company_id" not in metadata:
                    metadata["company_id"] = str(channel.company_id)
                
                # Clean the metadata to remove null, empty, and default values
                cleaned_metadata = clean_metadata(metadata)
                
                # For internal/bulk API: vault_storage_type and file_path for email attachments (S3 or local)
                vault_storage_type = datasource_data.storage_type
                file_path = None
                if datasource_data.storage_type == "local" and datasource_data.file_url:
                    # Email backend sent storage_type=local (FILE_UPLOAD_ENV=local): extract path from file_url for vault
                    try:
                        from urllib.parse import urlparse, unquote
                        parsed_url = urlparse(datasource_data.file_url)
                        file_path = unquote(parsed_url.path.lstrip("/"))
                        logger.info(f"[INTERNAL-BULK] Local storage: file_path from file_url: {file_path}")
                    except Exception as e:
                        logger.warning(f"Failed to extract file_path from local file_url: {e}")
                elif datasource_data.storage_type == "cloud" and datasource_data.provider == "s3" and datasource_data.file_url:
                    # Extract file_path from S3 URL (e.g., https://bucket.s3.amazonaws.com/path/to/file -> path/to/file)
                    try:
                        from urllib.parse import urlparse, unquote
                        parsed_url = urlparse(datasource_data.file_url)
                        # Get the path and remove leading slash
                        file_path = parsed_url.path.lstrip('/')
                        # URL decode the path to handle special characters
                        file_path = unquote(file_path)
                        # If URL contains bucket name in hostname (e.g., bucket.s3.amazonaws.com), remove it from path if present
                        if parsed_url.hostname and '.s3.' in parsed_url.hostname:
                            bucket_name = parsed_url.hostname.split('.')[0]
                            # Remove bucket name prefix if it exists in the path
                            if file_path.startswith(bucket_name + '/'):
                                file_path = file_path[len(bucket_name) + 1:]
                        # Treat as local storage for vault purposes
                        vault_storage_type = "local"
                        logger.info(f"[INTERNAL-BULK] Treating cloud S3 file as local storage. Extracted file_path: {file_path}")
                    except Exception as e:
                        logger.warning(f"Failed to extract file_path from file_url: {e}")
                        # Continue with original storage_type if extraction fails
                
                # Enhance metadata with vault-specific fields AFTER cleaning
                enhanced_metadata = await enhance_datasource_metadata(
                    existing_metadata=cleaned_metadata,
                    storage_type=vault_storage_type,  # Use vault_storage_type (may be "local" for email attachments)
                    provider=datasource_data.provider,
                    config=datasource_data.config.dict() if datasource_data.config else None,
                    app_type=getattr(datasource_data, 'app_type', None),
                    db=db,
                    channel_id=str(thread.channel_id),
                    location=getattr(datasource_data, 'location', None),
                    accessToken=getattr(datasource_data, 'accessToken', None)
                )
                if enhanced_metadata:
                    enhanced_metadata["thread_id"] = str(thread_uuid)
                    enhanced_metadata["company_id"] = str(channel.company_id)  # Ensure company_id is in enhanced metadata
                    
                    # For email attachments treated as local storage: ensure databaseType matches storageType
                    if vault_storage_type == "local":
                        enhanced_metadata["databaseType"] = "local"
                        # Add file_path to credentials if extracted from file_url (for S3/local storage)
                        if file_path:
                            if "credentials" not in enhanced_metadata:
                                enhanced_metadata["credentials"] = {}
                            enhanced_metadata["credentials"]["file_path"] = file_path
                        # Add file_url so Giggso-AI-ML can fetch directly (FILE_UPLOAD_ENV=local: LOCAL_FILES_URL + path)
                        if datasource_data.file_url:
                            enhanced_metadata["file_url"] = datasource_data.file_url

                # Handle vault integration for datasource metadata
                vault_unique_id = None
                giggso_vault_id = None
                if enhanced_metadata:
                    vault_required = True
                    try:
                        vault_result = await handle_vault_integration(
                            datasource_metadata=enhanced_metadata,
                            user_id=str(user.id),
                            company_id=str(channel.company_id),
                            db=db,
                            required=vault_required
                        )
                        vault_unique_id = vault_result["vault_unique_id"] if vault_result else None
                        giggso_vault_id = vault_result["giggso_vault_id"] if vault_result else None

                        if not vault_unique_id:
                            failed_datasources.append({"name": datasource_data.name or "Unknown", "error": "Vault integration failed. Cannot create datasource without secure storage."})
                            continue
                    except HTTPException as e:
                        failed_datasources.append({"name": datasource_data.name or "Unknown", "error": f"Vault integration failed: {e.detail}"})
                        continue
                    except Exception as e:
                        logger.error(f"Unexpected error during vault integration: {str(e)}", exc_info=True)
                        failed_datasources.append({"name": datasource_data.name or "Unknown", "error": "Failed to integrate with vault service"})
                        continue

                final_metadata = enhanced_metadata.copy()
                if vault_unique_id:
                    final_metadata["vault_unique_id"] = str(vault_unique_id)

                # Create datasource
                datasource = Datasource(
                    id=str(uuid.uuid4()),
                    name=datasource_name,
                    filename=filename,
                    storage_type=datasource_data.storage_type,
                    provider=datasource_data.provider,
                    app_type=datasource_data.app_type,
                    log_type=datasource_data.log_type,
                    config=datasource_data.config.dict() if datasource_data.config else None,
                    datasource_metadata=final_metadata,
                    giggso_vault_id=giggso_vault_id,
                    file_size=datasource_data.file_size or 0,
                    file_type=datasource_data.file_type or "application/octet-stream",
                    file_url=datasource_data.file_url,
                    channel_id=thread.channel_id,
                    added_by=user.id,
                    is_embedding_required=datasource_data.is_embedding_required or False,
                    embedding_status=1 if (datasource_data.is_embedding_required or False) else 0
                )

                db.add(datasource)
                await db.commit()
                await db.refresh(datasource)
                
                logger.info(f"✅ Created datasource: {datasource_name} (id={datasource.id}, thread_id={thread_uuid})")

                created_datasources.append({
                    "id": str(datasource.id),
                    "name": datasource.name,
                    "filename": datasource.filename,
                    "storage_type": datasource.storage_type,
                    "provider": datasource.provider,
                    "app_type": datasource.app_type,
                    "config": datasource.config,
                    "datasource_metadata": sanitize_datasource_metadata(datasource.datasource_metadata),
                    "giggso_vault_id": str(datasource.giggso_vault_id) if datasource.giggso_vault_id else None,
                    "file_size": datasource.file_size,
                    "file_type": datasource.file_type,
                    "file_url": datasource.file_url,
                    "channel_id": str(datasource.channel_id),
                    "workspace_id": str(thread.workspace_id),
                    "company_id": str(channel.company_id),
                    "added_by": str(datasource.added_by),
                    "is_active": datasource.is_active,
                    "is_connected": datasource.is_connected,
                    "is_processed": datasource.is_processed,
                    "processing_status": datasource.processing_status,
                    "error_message": datasource.error_message,
                    "last_processed_at": datasource.last_processed_at,
                    "processing_time": datasource.processing_time,
                    "record_count": datasource.record_count,
                    "is_embedding_required": datasource.is_embedding_required,
                    "embedding_status": datasource.embedding_status,
                    "created_at": datasource.created_at,
                    "updated_at": datasource.updated_at
                })

            except Exception as e:
                logger.error(f"Error processing datasource in internal bulk API: {str(e)}", exc_info=True)
                failed_datasources.append({"name": datasource_data.name or "Unknown", "error": str(e)})

        # Check if any datasources require embedding processing
        embedding_required_datasources = [ds for ds in created_datasources if ds.get("is_embedding_required", False)]

        if embedding_required_datasources:
            giggso_vault_ids = []
            for ds in embedding_required_datasources:
                if ds.get("giggso_vault_id"):
                    giggso_vault_ids.append(ds["giggso_vault_id"])

            vault_unique_ids = []
            vault_records = []
            if giggso_vault_ids:
                stmt = select(GiggsoVault).where(GiggsoVault.giggso_vault_id.in_(giggso_vault_ids))
                result = await db.execute(stmt)
                vault_records = result.scalars().all()
                vault_unique_ids = [record.vault_unique_id for record in vault_records if record.vault_unique_id]

                logger.info("=" * 80)
                logger.info("🔍 VAULT ID CONVERSION (INTERNAL API)")
                logger.info("=" * 80)
                logger.info(f"📊 Found {len(embedding_required_datasources)} datasources requiring embedding")
                logger.info(f"🔑 giggso_vault_ids: {giggso_vault_ids}")
                logger.info(f"📦 vault_unique_ids: {vault_unique_ids}")
                logger.info("=" * 80)

            if vault_unique_ids:
                first_datasource = embedding_required_datasources[0]
                channel_id = first_datasource.get("channel_id")
                user_id = first_datasource.get("added_by")
                company_id = first_datasource.get("company_id")

                if not user_id or not company_id:
                    logger.error(f"❌ Cannot proceed with embedding - missing user_id or company_id")
                    logger.error(f"   user_id: {user_id}, company_id: {company_id}")
                else:
                    # Classify each datasource by embedd_type and group them
                    from app.services.ml_service import get_embedd_type_from_file_type
                    
                    # Create a mapping from giggso_vault_id to vault_unique_id
                    vault_id_mapping = {}
                    for ds in embedding_required_datasources:
                        giggso_vault_id = ds.get("giggso_vault_id")
                        if giggso_vault_id:
                            # Find corresponding vault_unique_id
                            for record in vault_records:
                                # Convert both to strings for comparison to handle UUID vs string mismatches
                                if str(record.giggso_vault_id) == str(giggso_vault_id):
                                    vault_id_mapping[str(giggso_vault_id)] = record.vault_unique_id
                                    break
                    
                    logger.debug(f"🔍 Vault ID Mapping created (Internal): {len(vault_id_mapping)} mappings")
                    logger.debug(f"   Mapping keys: {list(vault_id_mapping.keys())}")
                    
                    # Group datasources by embedd_type
                    textual_datasources = []
                    tabular_datasources = []
                    
                    for ds in embedding_required_datasources:
                        # Determine embedd_type for this datasource
                        embedd_type = get_embedd_type_from_file_type(
                            file_type=ds.get("file_type"),
                            storage_type=ds.get("storage_type"),
                            provider=ds.get("provider")
                        )
                        
                        # Extract base type (remove provider suffix if any)
                        base_type = embedd_type.split("_")[0]
                        
                        # Group by base type
                        if base_type == "tabular":
                            tabular_datasources.append({
                                "datasource": ds,
                                "giggso_vault_id": ds.get("giggso_vault_id"),
                                "embedd_type": embedd_type
                            })
                        else:
                            # Default to textual for unknown types or textual files
                            textual_datasources.append({
                                "datasource": ds,
                                "giggso_vault_id": ds.get("giggso_vault_id"),
                                "embedd_type": embedd_type
                            })
                    
                    logger.info("=" * 80)
                    logger.info("📊 FILE CLASSIFICATION FOR BULK EMBEDDING (INTERNAL API)")
                    logger.info("=" * 80)
                    logger.info(f"📄 Textual files: {len(textual_datasources)}")
                    logger.info(f"📊 Tabular files: {len(tabular_datasources)}")
                    logger.info("=" * 80)
                    
                    # Internal/bulk = thread-level: extract thread_id from first datasource metadata (all have thread_id)
                    thread_id_for_embedding = None
                    first_ds_meta = embedding_required_datasources[0].get("datasource_metadata") or {}
                    if isinstance(first_ds_meta, dict) and first_ds_meta.get("thread_id"):
                        thread_id_for_embedding = first_ds_meta.get("thread_id")
                        logger.info(f"🧵 Thread-level embedding scope for internal/bulk: thread_id={thread_id_for_embedding}")
                    
                    # Use thread-level completed embeddings when thread_id present; else channel-level
                    if thread_id_for_embedding:
                        embedded_vault_unique_ids = await get_completed_embeddings_by_thread(thread_id_for_embedding, db)
                    else:
                        embedded_vault_unique_ids = await get_completed_embeddings_by_channel(channel_id, db)
                    jwt_token = settings.ML_API_KEY if settings.ML_API_KEY else None
                    # Fetch OpenAI vault token (gpt_token) for company to send to ML API
                    openai_vault_token = await get_openai_vault_token_for_company(db, company_id)

                    # Process textual files group
                    if textual_datasources:
                        textual_vault_unique_ids = [
                            vault_id_mapping[str(ds["giggso_vault_id"])]
                            for ds in textual_datasources
                            if ds["giggso_vault_id"] and str(ds["giggso_vault_id"]) in vault_id_mapping
                        ]
                        
                        logger.debug(f"📄 Textual vault_unique_ids (Internal): {textual_vault_unique_ids}")
                        
                        if textual_vault_unique_ids:
                            textual_ds_list = [ds["datasource"] for ds in textual_datasources]
                            
                            # Extract table_name from first textual datasource metadata that has it
                            table_name = None
                            for ds in textual_datasources:
                                metadata = ds["datasource"].get("datasource_metadata")
                                if metadata and isinstance(metadata, dict):
                                    table_name = metadata.get("tableName")
                                    if table_name:
                                        break
                            
                            try:
                                table_names = extract_table_names_from_datasources(textual_ds_list) if len(textual_ds_list) > 1 else None
                                logger.info(f"🚀 Calling ML API for {len(textual_vault_unique_ids)} textual file(s) with embedd_type='textual'")
                                
                                result = await ml_service.request_embedding_processing(
                                    vault_unique_ids=textual_vault_unique_ids,
                                    user_id=user_id,
                                    company_id=company_id,
                                    channel_id=channel_id,
                                    embedded_vault_unique_ids=embedded_vault_unique_ids,
                                    jwt_token=jwt_token,
                                    embedd_type="textual",
                                    table_name=table_name,
                                    table_names=table_names,
                                    thread_id=thread_id_for_embedding,
                                    openai_vault_token=openai_vault_token
                                )
                                
                                # Emit socket event based on ML API response
                                socket_service = get_socket_service()
                                if socket_service.is_socket_connected():
                                    ml_status = 2 if result.get("success") else 3
                                    
                                    # Emit socket event for each textual datasource
                                    for ds in textual_datasources:
                                        datasource_id = ds["datasource"].get("id")
                                        if datasource_id:
                                            socket_event_data = {"type": 16, "data": {"channelId": channel_id, "status": ml_status, "datasourceId": datasource_id}}
                                            try:
                                                await socket_service.emit("shay_realtime", socket_event_data)
                                                logger.info(f"✅ Emitted socket event for textual datasource {datasource_id}: status={ml_status}")
                                            except Exception as socket_error:
                                                logger.error(f"❌ Failed to emit socket event for datasource {datasource_id}: {socket_error}")
                                
                                if result.get("success"):
                                    logger.info(f"✅ ML API call successful for {len(textual_vault_unique_ids)} textual file(s)")
                                else:
                                    logger.error(f"❌ ML API call failed for textual files: {result.get('message', 'Unknown error')}")
                                    
                            except Exception as e:
                                logger.error(f"❌ Error calling ML API for textual files: {e}")
                                
                                # Emit socket event for failure
                                socket_service = get_socket_service()
                                if socket_service.is_socket_connected():
                                    for ds in textual_datasources:
                                        datasource_id = ds["datasource"].get("id")
                                        if datasource_id:
                                            try:
                                                await socket_service.emit("shay_realtime", {
                                                    "type": 16,
                                                    "data": {
                                                        "channelId": channel_id,
                                                        "status": 3,  # failure
                                                        "datasourceId": datasource_id
                                                    }
                                                })
                                            except Exception:
                                                pass
                    
                    # Process tabular files group
                    if tabular_datasources:
                        tabular_vault_unique_ids = [
                            vault_id_mapping[str(ds["giggso_vault_id"])]
                            for ds in tabular_datasources
                            if ds["giggso_vault_id"] and str(ds["giggso_vault_id"]) in vault_id_mapping
                        ]
                        
                        logger.debug(f"📊 Tabular vault_unique_ids (Internal): {tabular_vault_unique_ids}")
                        
                        if tabular_vault_unique_ids:
                            tabular_ds_list = [ds["datasource"] for ds in tabular_datasources]
                            
                            # Extract table_name from first tabular datasource metadata that has it
                            table_name = None
                            for ds in tabular_datasources:
                                metadata = ds["datasource"].get("datasource_metadata")
                                if metadata and isinstance(metadata, dict):
                                    table_name = metadata.get("tableName")
                                    if table_name:
                                        break
                            
                            try:
                                table_names = extract_table_names_from_datasources(tabular_ds_list) if len(tabular_ds_list) > 1 else None
                                logger.info(f"🚀 Calling ML API for {len(tabular_vault_unique_ids)} tabular file(s) with embedd_type='tabular'")
                                
                                result = await ml_service.request_embedding_processing(
                                    vault_unique_ids=tabular_vault_unique_ids,
                                    user_id=user_id,
                                    company_id=company_id,
                                    channel_id=channel_id,
                                    embedded_vault_unique_ids=embedded_vault_unique_ids,
                                    jwt_token=jwt_token,
                                    embedd_type="tabular",
                                    table_name=table_name,
                                    table_names=table_names,
                                    thread_id=thread_id_for_embedding,
                                    openai_vault_token=openai_vault_token
                                )
                                
                                # Emit socket event based on ML API response
                                socket_service = get_socket_service()
                                if socket_service.is_socket_connected():
                                    ml_status = 2 if result.get("success") else 3
                                    
                                    # Emit socket event for each tabular datasource
                                    for ds in tabular_datasources:
                                        datasource_id = ds["datasource"].get("id")
                                        if datasource_id:
                                            socket_event_data = {"type": 16, "data": {"channelId": channel_id, "status": ml_status, "datasourceId": datasource_id}}
                                            try:
                                                await socket_service.emit("shay_realtime", socket_event_data)
                                                logger.info(f"✅ Emitted socket event for tabular datasource {datasource_id}: status={ml_status}")
                                            except Exception as socket_error:
                                                logger.error(f"❌ Failed to emit socket event for datasource {datasource_id}: {socket_error}")
                                
                                if result.get("success"):
                                    logger.info(f"✅ ML API call successful for {len(tabular_vault_unique_ids)} tabular file(s)")
                                else:
                                    logger.error(f"❌ ML API call failed for tabular files: {result.get('message', 'Unknown error')}")
                                    
                            except Exception as e:
                                logger.error(f"❌ Error calling ML API for tabular files: {e}")
                                
                                # Emit socket event for failure
                                socket_service = get_socket_service()
                                if socket_service.is_socket_connected():
                                    for ds in tabular_datasources:
                                        datasource_id = ds["datasource"].get("id")
                                        if datasource_id:
                                            try:
                                                await socket_service.emit("shay_realtime", {
                                                    "type": 16,
                                                    "data": {
                                                        "channelId": channel_id,
                                                        "status": 3,  # failure
                                                        "datasourceId": datasource_id
                                                    }
                                                })
                                            except Exception:
                                                pass
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
