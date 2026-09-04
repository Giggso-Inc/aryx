"""
Datasource CRUD + listing/stats endpoints.
"""

import logging
import os
import uuid
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import String, and_, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.expression import literal

from app.core.config import settings
from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.channel import Channel
from app.models.channel_member import ChannelMember
from app.models.datasource import Datasource
from app.models.giggso_vault import GiggsoVault
from app.models.user import User
from app.schemas.datasource import (
    DatasourceCreate,
    DatasourceListWithRelations,
    DatasourceResponse,
    DatasourceStats,
    DatasourceTypeCount,
    DatasourceTypeCountResponse,
    DatasourceUpdate,
)
from app.services.ml_service import extract_table_names_from_datasources, ml_service
from app.services.socket_client_service import get_socket_service
from app.services.vault_data_builder import enhance_datasource_metadata
from app.utils.channel_access import check_channel_access, check_channel_access_by_thread

from ._shared import (
    _aryx_ingestion_status_for,
    clean_metadata,
    generate_datasource_metadata,
    get_completed_embeddings_by_channel,
    get_openai_vault_token_for_company,
    handle_vault_integration,
    sanitize_datasource_metadata,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/supported-log-types", response_model=List[str])
async def get_supported_log_types() -> List[str]:
    """Get list of supported log types configured in environment"""
    return settings.SUPPORTED_LOG_TYPES

@router.post("/", response_model=DatasourceResponse)
async def create_datasource(
    datasource_data: DatasourceCreate,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> DatasourceResponse:
    """Create a single datasource"""
    user = await get_current_user_required(request)
    
    # Get channel
    stmt = select(Channel).where(Channel.id == datasource_data.channel_id)
    result = await db.execute(stmt)
    channel = result.scalar_one_or_none()
    
    if not channel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Channel not found"
        )
    
    # Check permissions
    if not channel.is_accessible_by_user(user.company_id, user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to channel"
        )
    
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
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Datasource with name '{datasource_data.name}' already exists in this channel"
        )
    
    # Validate storage type specific requirements
    if datasource_data.storage_type == "cloud" and not datasource_data.provider:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provider is required for cloud storage type"
        )
    
    if datasource_data.storage_type == "app" and not datasource_data.app_type:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="App type is required for app storage type"
        )
    
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
            datasource_name = "Cloud Datasource"  # Default name
    
    # Get filename (either provided or extract from URL/location) - MUST be done BEFORE generating metadata
    filename = datasource_data.filename
    if not filename:
        if datasource_data.file_url:
            filename = os.path.basename(datasource_data.file_url.split('?')[0])  # Remove query params
            if not filename:
                filename = "cloud_file"  # Fallback name
        elif datasource_data.location:
            # Extract filename from location (gs://, s3://, https://, etc.)
            location = datasource_data.location
            # Remove protocol prefix (gs://, s3://, https://, etc.)
            if "://" in location:
                path_part = location.split("://", 1)[1]
                # Remove bucket name (first part before /)
                if "/" in path_part:
                    file_path = "/".join(path_part.split("/")[1:])
                    filename = os.path.basename(file_path) if file_path else None
                else:
                    filename = None
            else:
                filename = os.path.basename(location)
            
            if not filename:
                filename = "cloud_file"  # Fallback name
        elif datasource_data.storage_type == "database":
            provider = datasource_data.provider or "database"
            db_name = datasource_data.name or f"{provider}_connection"
            filename = "".join(c for c in db_name if c.isalnum() or c in (' ', '-', '_')).strip()
            if not filename:
                filename = f"{provider}_datasource"
            if not filename.endswith(('.db', '.sql', '.csv')):
                filename = f"{filename}.db"
        else:
            filename = datasource_data.name or "datasource"
            filename = "".join(c for c in filename if c.isalnum() or c in (' ', '-', '_')).strip()
            if not filename:
                filename = "datasource"
    
    # Generate metadata structure (now with extracted filename)
    metadata = generate_datasource_metadata(
        filename=filename,  # Use extracted filename instead of datasource_data.filename
        storage_type=datasource_data.storage_type,
        channel_id=datasource_data.channel_id,
        workspace_id=str(channel.workspace_id),
        user_id=str(user.id),
        file_size=datasource_data.file_size,
        file_type=datasource_data.file_type,
        provider=datasource_data.provider,
        app_type=datasource_data.app_type,
        log_type=datasource_data.log_type,
        config=datasource_data.config.dict() if datasource_data.config else None,
        file_url=datasource_data.file_url,
        is_embedding_required=datasource_data.is_embedding_required or False
    )
    
    # Clean the metadata to remove null, empty, and default values
    cleaned_metadata = clean_metadata(metadata)
    
    # Enhance metadata for database, cloud, and app storage types (all require vault integration)
    if datasource_data.storage_type in ["database", "cloud", "app"]:
        
        enhanced_metadata = await enhance_datasource_metadata(
            existing_metadata=cleaned_metadata,
            storage_type=datasource_data.storage_type,
            provider=datasource_data.provider,
            config=datasource_data.config.dict() if datasource_data.config else None,
            app_type=datasource_data.app_type,
            db=db,
            channel_id=datasource_data.channel_id,
            location=datasource_data.location,
            accessToken=datasource_data.accessToken
        )
        # Use enhanced metadata for vault storage
        cleaned_metadata = enhanced_metadata
    
    # Handle vault integration for datasource metadata
    vault_unique_id = None
    if cleaned_metadata:
        # For cloud and database datasources (which contain sensitive credentials), vault integration is required
        # For local file uploads, vault integration is optional
        vault_required = datasource_data.storage_type in ["cloud", "database", "app"]
        
        try:
            vault_result = await handle_vault_integration(
                datasource_metadata=cleaned_metadata,
                user_id=str(user.id),
                company_id=str(channel.company_id),
                db=db,
                required=vault_required
            )
            vault_unique_id = vault_result["vault_unique_id"] if vault_result else None
            giggso_vault_id = vault_result["giggso_vault_id"] if vault_result else None
        except HTTPException as e:
            # Re-raise HTTPException for required vault integration
            raise e
        except Exception as e:
            # For unexpected errors, log and fail
            print(f"Unexpected error during vault integration: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to integrate with vault service"
            )
    
    # Store cleaned metadata directly in database (with vault integration for backup)
    final_metadata = cleaned_metadata.copy()
    if vault_unique_id:
        final_metadata["vault_unique_id"] = str(vault_unique_id)
    
    # Create datasource (without redundant workspace_id and company_id)
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
        file_size=datasource_data.file_size,
        file_type=datasource_data.file_type,
        file_url=datasource_data.file_url,
        channel_id=datasource_data.channel_id,
        added_by=user.id,
        is_embedding_required=datasource_data.is_embedding_required or False,
        embedding_status=1 if (datasource_data.is_embedding_required or False) else 0
    )
    
    db.add(datasource)
    # Flush to ensure the record is sent to the database before commit
    # This is important for Oracle and other databases that require explicit flushing
    await db.flush()
    await db.commit()
    await db.refresh(datasource)
    
    # Verify vault record still exists after datasource creation
    # This ensures the vault record commit persisted and wasn't rolled back
    if vault_unique_id:
        vault_verify_stmt = select(GiggsoVault).where(
            GiggsoVault.vault_unique_id == vault_unique_id
        )
        vault_verify_result = await db.execute(vault_verify_stmt)
        vault_verified = vault_verify_result.scalar_one_or_none()
        
        if not vault_verified:
            print(f"ERROR: Vault record {vault_unique_id} not found after datasource creation!")
            print(f"ERROR: This indicates the vault record commit was rolled back or did not persist")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Critical error: Vault record was lost after datasource creation. Vault ID: {vault_unique_id}"
            )
        else:
            print(f"✅ Verified vault record still exists after datasource creation: {vault_unique_id}")
    
    # Log success message with vault ID if available
    if vault_unique_id:
        logger.debug(f"Successfully stored datasource in backend. Vault ID: {vault_unique_id}")
    
    # Trigger embedding if required
    if datasource.is_embedding_required and vault_unique_id and datasource.giggso_vault_id:
        try:
            # Get vault_unique_id from gg_vault table
            vault_stmt = select(GiggsoVault).where(GiggsoVault.giggso_vault_id == datasource.giggso_vault_id)
            vault_result = await db.execute(vault_stmt)
            vault_record = vault_result.scalar_one_or_none()
            
            if vault_record and vault_record.vault_unique_id:
                # Determine embedd_type based on file type, storage type, and provider
                from app.services.ml_service import get_embedd_type_from_file_type
                embedd_type = get_embedd_type_from_file_type(
                    file_type=datasource.file_type,
                    storage_type=datasource.storage_type,
                    provider=datasource.provider
                )
                
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
                
                logger.info(f"Triggering embedding for datasource {datasource.id}, embedd_type: {embedd_type}")
                
                # Fetch OpenAI vault token (gpt_token) for company to send to ML API
                openai_vault_token = await get_openai_vault_token_for_company(db, str(user.company_id))
                # Call ML API to request embedding processing
                table_names = extract_table_names_from_datasources([datasource]) if table_name is None else None
                result = await ml_service.request_embedding_processing(
                    vault_unique_ids=[vault_record.vault_unique_id],
                    user_id=str(user.id),
                    company_id=str(user.company_id),
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
                    ml_status = 2 if result.get("success") else 3
                    socket_event_data = {
                        "type": 16,
                        "data": {
                            "channelId": str(datasource.channel_id),
                            "status": ml_status,
                            "datasourceId": str(datasource.id)
                        }
                    }
                    socket_service.emit("datasource_event", socket_event_data)
            else:
                logger.warning(f"Vault record not found for giggso_vault_id: {datasource.giggso_vault_id}")
        except Exception as e:
            logger.error(f"Error triggering embedding for datasource {datasource.id}: {e}", exc_info=True)
    
    return DatasourceResponse(
        id=str(datasource.id),
        name=datasource.name,
        filename=datasource.filename,
        storage_type=datasource.storage_type,
        provider=datasource.provider,
        app_type=datasource.app_type,
        config=datasource.config,
        datasource_metadata=sanitize_datasource_metadata(datasource.datasource_metadata),
        giggso_vault_id=str(datasource.giggso_vault_id) if datasource.giggso_vault_id else None,
        file_size=datasource.file_size,
        file_type=datasource.file_type,
        file_url=datasource.file_url,
        channel_id=str(datasource.channel_id),
        workspace_id=str(channel.workspace_id),
        company_id=str(channel.company_id),
        added_by=str(datasource.added_by),
        is_active=datasource.is_active,
        is_connected=datasource.is_connected,
        is_processed=datasource.is_processed,
        processing_status=datasource.processing_status,
        error_message=datasource.error_message,
        last_processed_at=datasource.last_processed_at,
        processing_time=datasource.processing_time,
        record_count=datasource.record_count,
        is_embedding_required=datasource.is_embedding_required,
        embedding_status=datasource.embedding_status,
        created_at=datasource.created_at,
        updated_at=datasource.updated_at
    )

@router.get("/environment", response_model=Dict[str, Any])
async def get_environment_config() -> Dict[str, Any]:
    """Get current environment configuration for debugging vault settings"""
    from app.services.vault_data_builder import get_environment_info
    return get_environment_info()

@router.get("/", response_model=DatasourceListWithRelations)
async def list_datasources(
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    channel_id: Optional[str] = None,
    thread_id: Optional[str] = Query(None, description="Filter by thread ID. When set, returns only thread-level datasources for this thread. When omitted, channel-level list excludes thread-level (e.g. email attachment) datasources."),
    storage_type: Optional[str] = Query(None, description="Filter by storage type: local, cloud, db, app"),
    data_source_type: Optional[str] = Query(None, description="Alias for storage_type. Filter by data source type: local, cloud, db, app"),
    provider: Optional[str] = None,
    app_type: Optional[str] = None,
    processing_status: Optional[str] = None,
    is_connected: Optional[bool] = Query(None, description="Filter by connection status. True for connected, False for disconnected"),
    search: Optional[str] = None
) -> DatasourceListWithRelations:
    """List datasources with filtering and pagination
    
    Supports filtering by data source type (storage_type or data_source_type):
    - local: Local file uploads
    - cloud: Cloud storage (S3, Azure, etc.)
    - db: Database connections
    - app: App-based sources (Google Drive, SharePoint, etc.)
    
    Thread-level vs channel-level: Attachment datasources from email sync are stored as
    thread-level (datasource_metadata.thread_id set). When listing by channel without
    thread_id, only channel-level datasources are returned. Pass thread_id to get
    datasources for a specific thread (e.g. email attachments in that thread).
    """
    user = await get_current_user_required(request)
    
    # If channel_id is provided, check channel access first
    if channel_id:
        await check_channel_access(db, user, channel_id)
    
    # Build base query - filter by user's company and only channels user is a member of (gg_channel_members)
    query = (
        select(Datasource)
        .join(Datasource.channel)
        .where(Channel.company_id == user.company_id)
        .join(
            ChannelMember,
            and_(
                ChannelMember.channel_id == Datasource.channel_id,
                ChannelMember.user_id == user.id,
                ChannelMember.is_active == True,
            ),
        )
    )
    
    # Exclude database datasources without a tableName (incomplete database connections)
    # Database datasources should have a tableName in config or datasource_metadata
    query = query.where(
        or_(
            Datasource.storage_type != "database",
            and_(
                Datasource.storage_type == "database",
                or_(
                    and_(
                        Datasource.config.op("?")(literal("tableName", type_=String())),
                        Datasource.config.op("->>")(literal("tableName", type_=String())).isnot(None),
                        Datasource.config.op("->>")(literal("tableName", type_=String())) != literal("", type_=String())
                    ),
                    and_(
                        Datasource.datasource_metadata.op("?")(literal("tableName", type_=String())),
                        Datasource.datasource_metadata.op("->>")(literal("tableName", type_=String())).isnot(None),
                        Datasource.datasource_metadata.op("->>")(literal("tableName", type_=String())) != literal("", type_=String())
                    )
                )
            )
        )
    )
    
    # Thread-level vs channel-level: attachment datasources from email sync have
    # datasource_metadata.thread_id set. When listing by channel without thread_id,
    # exclude thread-level so channel view shows only channel-level datasources.
    if thread_id:
        # Return only datasources for this thread (e.g. email attachments in thread)
        try:
            thread_uuid = uuid.UUID(thread_id)
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid thread_id format: {thread_id}"
            )
        await check_channel_access_by_thread(db, user, thread_id)
        query = query.where(
            and_(
                Datasource.datasource_metadata.isnot(None),
                Datasource.datasource_metadata.op("?")(literal("thread_id", type_=String())),
                Datasource.datasource_metadata.op("->>")(literal("thread_id", type_=String())) == literal(str(thread_uuid), type_=String())
            )
        )
        # Include all thread-level datasources (any embedding status) so new local/S3 attachments show immediately
        # Embedding can complete in background; no filter by embedding_status here
    else:
        # Exclude thread-level datasources so channel list shows only channel-level
        query = query.where(
            or_(
                Datasource.datasource_metadata.is_(None),
                ~Datasource.datasource_metadata.op("?")(literal("thread_id", type_=String()))
            )
        )
    
    # Apply filters
    if channel_id:
        # Convert channel_id to UUID if it's a string
        channel_uuid = channel_id
        if isinstance(channel_id, str):
            try:
                channel_uuid = uuid.UUID(channel_id)
            except (ValueError, AttributeError):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid channel_id format: {channel_id}"
                )
        query = query.where(Datasource.channel_id == channel_uuid)
    
    # Use data_source_type if provided, otherwise use storage_type
    type_filter = data_source_type if data_source_type else storage_type
    if type_filter:
        query = query.where(Datasource.storage_type == type_filter)
    
    if provider:
        query = query.where(Datasource.provider == provider)
    
    if app_type:
        query = query.where(Datasource.app_type == app_type)
    
    if processing_status:
        query = query.where(Datasource.processing_status == processing_status)
    
    if is_connected is not None:
        query = query.where(Datasource.is_connected == is_connected)
    
    if search:
        search_filter = or_(
            Datasource.name.ilike(f"%{search}%"),
            Datasource.filename.ilike(f"%{search}%")
        )
        query = query.where(search_filter)
    
    # Get total count - same as main query: company + channel membership
    count_query = (
        select(func.count(Datasource.id))
        .join(Datasource.channel)
        .where(Channel.company_id == user.company_id)
        .join(
            ChannelMember,
            and_(
                ChannelMember.channel_id == Datasource.channel_id,
                ChannelMember.user_id == user.id,
                ChannelMember.is_active == True,
            ),
        )
    )
    
    # Apply same filter to exclude database datasources without tableName
    count_query = count_query.where(
        or_(
            Datasource.storage_type != "database",
            and_(
                Datasource.storage_type == "database",
                or_(
                    and_(
                        Datasource.config.op("?")(literal("tableName", type_=String())),
                        Datasource.config.op("->>")(literal("tableName", type_=String())).isnot(None),
                        Datasource.config.op("->>")(literal("tableName", type_=String())) != literal("", type_=String())
                    ),
                    and_(
                        Datasource.datasource_metadata.op("?")(literal("tableName", type_=String())),
                        Datasource.datasource_metadata.op("->>")(literal("tableName", type_=String())).isnot(None),
                        Datasource.datasource_metadata.op("->>")(literal("tableName", type_=String())) != literal("", type_=String())
                    )
                )
            )
        )
    )
    
    # Apply same thread-level vs channel-level logic to count query
    if thread_id:
        count_query = count_query.where(
            and_(
                Datasource.datasource_metadata.isnot(None),
                Datasource.datasource_metadata.op("?")(literal("thread_id", type_=String())),
                Datasource.datasource_metadata.op("->>")(literal("thread_id", type_=String())) == literal(str(thread_uuid), type_=String())
            )
        )
        # No embedding filter for count: include all thread-level (matches main query)
    else:
        count_query = count_query.where(
            or_(
                Datasource.datasource_metadata.is_(None),
                ~Datasource.datasource_metadata.op("?")(literal("thread_id", type_=String()))
            )
        )
    
    # Apply same filters to count query
    if channel_id:
        count_query = count_query.where(Datasource.channel_id == channel_uuid)
    
    if type_filter:
        count_query = count_query.where(Datasource.storage_type == type_filter)
    
    if provider:
        count_query = count_query.where(Datasource.provider == provider)
    
    if app_type:
        count_query = count_query.where(Datasource.app_type == app_type)
    
    if processing_status:
        count_query = count_query.where(Datasource.processing_status == processing_status)
    
    if is_connected is not None:
        count_query = count_query.where(Datasource.is_connected == is_connected)
    
    if search:
        search_filter = or_(
            Datasource.name.ilike(f"%{search}%"),
            Datasource.filename.ilike(f"%{search}%")
        )
        count_query = count_query.where(search_filter)
    
    # Execute count query
    count_result = await db.execute(count_query)
    total_count = count_result.scalar()
    
    # Apply pagination and ordering (tie-break by id so "latest" is deterministic for same created_at)
    query = query.order_by(desc(Datasource.created_at), desc(Datasource.id))
    
    # For thread-level queries: deduplicate by filename; prefer embedding-completed when present, else latest
    # Same file can appear in multiple emails; return one row per filename so no duplicates
    if thread_id:
        result = await db.execute(query)
        all_datasources = result.scalars().all()
        # Sort: embedding_status==2 (completed) first, then by created_at desc, then id desc
        # So per filename we keep: completed row if any, else the latest row
        def _thread_ds_sort_key(ds) -> Tuple[int, float, str]:
            ts = ds.created_at.timestamp() if ds.created_at else 0
            return (0 if (ds.embedding_status == 2) else 1, -ts, str(ds.id or ""))

        all_datasources_sorted = sorted(all_datasources, key=_thread_ds_sort_key)
        seen_filenames = {}
        unique_datasources = []
        for ds in all_datasources_sorted:
            filename_key = (ds.filename or ds.name or "unknown").strip() or "unknown"
            if filename_key not in seen_filenames:
                seen_filenames[filename_key] = True
                unique_datasources.append(ds)

        total_count = len(unique_datasources)
        start_idx = (page - 1) * size
        end_idx = start_idx + size
        datasources = unique_datasources[start_idx:end_idx]
    else:
        # For channel-level queries: apply pagination normally
        query = query.offset((page - 1) * size).limit(size)
        result = await db.execute(query)
        datasources = result.scalars().all()
    
    # Fetch current user's channel memberships for all channels in this page (avoids N+1)
    unique_channel_ids = list({ds.channel_id for ds in datasources if ds.channel_id})
    members_map = {}  # channel_id -> ChannelMember for current user
    if unique_channel_ids:
        members_stmt = select(ChannelMember).where(
            and_(
                ChannelMember.channel_id.in_(unique_channel_ids),
                ChannelMember.user_id == user.id,
                ChannelMember.is_active == True
            )
        )
        members_result = await db.execute(members_stmt)
        for member in members_result.scalars().all():
            members_map[member.channel_id] = member
    
    # Convert to response format
    datasource_responses = []
    for datasource in datasources:
        # Get channel for workspace_id and company_id
        channel_stmt = select(Channel).where(Channel.id == datasource.channel_id)
        channel_result = await db.execute(channel_stmt)
        channel = channel_result.scalar_one_or_none()
        
        # Get user who added the datasource
        added_by_user = None
        if datasource.added_by:
            # Ensure added_by is a UUID object if it's a string
            added_by_id = datasource.added_by
            if isinstance(added_by_id, str):
                try:
                    added_by_id = uuid.UUID(added_by_id)
                except (ValueError, AttributeError):
                    added_by_id = None
            
            if added_by_id:
                user_stmt = select(User).where(User.id == added_by_id)
                user_result = await db.execute(user_stmt)
                added_by_user = user_result.scalar_one_or_none()
        
        # Convert channel to dict (include is_member and member_role from gg_channel_members)
        channel_dict = None
        if channel:
            member = members_map.get(channel.id)
            is_member = member is not None
            # member_role: "admin" or "user" per gg_channel_members.role
            member_role = ("admin" if member.role == "admin" else "user") if member else None
            channel_dict = {
                "id": str(channel.id),
                "name": channel.name,
                "description": channel.description,
                "workspace_id": str(channel.workspace_id),
                "workspace_name": getattr(channel, 'workspace_name', None),
                "company_id": str(channel.company_id),
                "is_active": channel.is_active,
                "is_public": channel.is_public,
                "ai_enabled": channel.ai_enabled,
                "channel_settings": channel.channel_settings,
                "message_count": getattr(channel, 'message_count', 0),
                "last_message_at": getattr(channel, 'last_message_at', None),
                "created_at": channel.created_at,
                "updated_at": channel.updated_at,
                "is_member": is_member,
                "member_role": member_role
            }
        
        # Convert user to dict
        user_dict = None
        if added_by_user:
            user_dict = {
                "user_id": str(added_by_user.id),
                "name": added_by_user.name,
                "email_id": added_by_user.email_id,
                "avatar_url": added_by_user.avatar_url,
                "company_id": str(added_by_user.company_id),
                "role": added_by_user.role,
                "created_datetime": added_by_user.created_datetime,
                "updated_datetime": added_by_user.updated_datetime
            }
        
        datasource_responses.append({
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
            "channel": channel_dict,  # Full channel object as dict
            "added_by_user": user_dict,  # Full user object as dict
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
    
    return DatasourceListWithRelations(
        datasources=datasource_responses,
        total=total_count,
        page=page,
        size=size,
        pages=(total_count + size - 1) // size
    )

@router.get("/stats", response_model=DatasourceStats)
async def get_datasource_stats(
    request: Request,
    db: AsyncSession = Depends(get_db),
    channel_id: Optional[str] = None
) -> DatasourceStats:
    """Get datasource statistics"""
    user = await get_current_user_required(request)
    
    # Build base query - filter by user's company through channel relationship
    base_query = select(Datasource).join(Datasource.channel).where(Channel.company_id == user.company_id)
    total_query = select(func.count(Datasource.id)).join(Datasource.channel).where(Channel.company_id == user.company_id)
    
    # Apply channel filter if provided
    if channel_id:
        # Convert channel_id to UUID if it's a string
        channel_uuid = channel_id
        if isinstance(channel_id, str):
            try:
                channel_uuid = uuid.UUID(channel_id)
            except (ValueError, AttributeError):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid channel_id format: {channel_id}"
                )
        base_query = base_query.where(Datasource.channel_id == channel_uuid)
        total_query = total_query.where(Datasource.channel_id == channel_uuid)
    
    # Exclude thread-level datasources (e.g. email attachments) from channel stats
    # so channel-level stats show only channel-level datasources
    base_query = base_query.where(
        or_(
            Datasource.datasource_metadata.is_(None),
            ~Datasource.datasource_metadata.op("?")(literal("thread_id", type_=String()))
        )
    )
    total_query = total_query.where(
        or_(
            Datasource.datasource_metadata.is_(None),
            ~Datasource.datasource_metadata.op("?")(literal("thread_id", type_=String()))
        )
    )
    
    # Get total count
    total_result = await db.execute(total_query)
    total_count = total_result.scalar()
    
    # Get active count
    active_query = base_query.where(and_(Datasource.is_active == True))
    active_result = await db.execute(active_query)
    active_count = len(active_result.scalars().all())
    
    # Get processed count
    processed_query = base_query.where(and_(Datasource.is_processed == True))
    processed_result = await db.execute(processed_query)
    processed_count = len(processed_result.scalars().all())
    
    # Get pending count
    pending_query = base_query.where(and_(Datasource.processing_status == "pending"))
    pending_result = await db.execute(pending_query)
    pending_count = len(pending_result.scalars().all())
    
    # Get failed count
    failed_query = base_query.where(and_(Datasource.processing_status == "failed"))
    failed_result = await db.execute(failed_query)
    failed_count = len(failed_result.scalars().all())
    
    # Get total file size
    size_query = base_query.where(and_(Datasource.file_size.isnot(None)))
    size_result = await db.execute(size_query)
    datasources_with_size = size_result.scalars().all()
    total_file_size = sum(ds.file_size for ds in datasources_with_size if ds.file_size)
    
    # Get storage type distribution

    # Use select() with columns directly for Core query (not with_entities which is ORM-only)
    storage_types_query = select(
        Datasource.storage_type,
        func.count(Datasource.id).label('count')
    ).join(Datasource.channel).where(
        Channel.company_id == user.company_id
    ).group_by(Datasource.storage_type)
    
    # Apply channel filter if provided
    if channel_id:
        storage_types_query = storage_types_query.where(Datasource.channel_id == channel_uuid)
    
    # Apply thread-level filtering
    storage_types_query = storage_types_query.where(
        or_(
            Datasource.datasource_metadata.is_(None),
            ~Datasource.datasource_metadata.op("?")(literal("thread_id", type_=String()))
        )
    )
    
    storage_types_result = await db.execute(storage_types_query)
    storage_types = {row.storage_type: row.count for row in storage_types_result}
    
    # Get provider distribution (for cloud storage)
    provider_query = base_query.where(and_(Datasource.provider.isnot(None)))
    provider_result = await db.execute(provider_query)
    providers = {}
    for datasource in provider_result.scalars().all():
        provider = datasource.provider
        providers[provider] = providers.get(provider, 0) + 1
    
    return DatasourceStats(
        total_datasources=total_count,
        active_datasources=active_count,
        processed_datasources=processed_count,
        pending_datasources=pending_count,
        failed_datasources=failed_count,
        total_file_size=total_file_size,
        storage_type_breakdown=storage_types,
        provider_breakdown=providers
    )

@router.get("/count", response_model=DatasourceTypeCountResponse)
async def get_datasource_type_count(
    request: Request,
    db: AsyncSession = Depends(get_db),
    channel_id: Optional[str] = None
) -> DatasourceTypeCountResponse:
    """Get count of connected data sources by type (local, cloud, db, app)"""
    user = await get_current_user_required(request)
    
    # Build base query - filter by user's company and connected status
    # Get counts grouped by storage_type
    count_query = select(
        Datasource.storage_type,
        func.count(Datasource.id).label('count')
    ).join(Datasource.channel).where(
        and_(
            Channel.company_id == user.company_id,
            Datasource.is_connected == True
        )
    ).group_by(Datasource.storage_type)
    
    # Apply channel filter if provided
    if channel_id:
        # Convert channel_id to UUID if it's a string
        channel_uuid = channel_id
        if isinstance(channel_id, str):
            try:
                channel_uuid = uuid.UUID(channel_id)
            except (ValueError, AttributeError):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid channel_id format: {channel_id}"
                )
        count_query = count_query.where(Datasource.channel_id == channel_uuid)
    
    # Exclude thread-level datasources (e.g. email attachments) from type count
    # so channel-level count shows only channel-level datasources
    count_query = count_query.where(
        or_(
            Datasource.datasource_metadata.is_(None),
            ~Datasource.datasource_metadata.op("?")(literal("thread_id", type_=String()))
        )
    )
    
    # Execute query to get counts by type
    result = await db.execute(count_query)
    type_counts = {row.storage_type: row.count for row in result}
    
    # Define the data source types to include in response
    data_source_types = ["local", "cloud", "app", "db"]
    
    counts = []
    total_connected = 0
    
    # Build response with counts for each type (0 if not found)
    for ds_type in data_source_types:
        count = type_counts.get(ds_type, 0)
        total_connected += count
        counts.append(DatasourceTypeCount(type=ds_type, count=count))
    
    return DatasourceTypeCountResponse(
        counts=counts,
        total_connected=total_connected
    )

@router.get("/{datasource_id}", response_model=DatasourceResponse)
async def get_datasource(
    datasource_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> DatasourceResponse:
    """Get a specific datasource by ID"""
    user = await get_current_user_required(request)
    
    # Get datasource with channel
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
    
    # Get channel for workspace_id and company_id
    channel_stmt = select(Channel).where(Channel.id == datasource.channel_id)
    channel_result = await db.execute(channel_stmt)
    channel = channel_result.scalar_one_or_none()
    
    return DatasourceResponse(
        id=str(datasource.id),
        name=datasource.name,
        filename=datasource.filename,
        storage_type=datasource.storage_type,
        provider=datasource.provider,
        app_type=datasource.app_type,
        config=datasource.config,
        datasource_metadata=sanitize_datasource_metadata(datasource.datasource_metadata),
        file_size=datasource.file_size,
        file_type=datasource.file_type,
        file_url=datasource.file_url,
        channel_id=str(datasource.channel_id),
        workspace_id=str(channel.workspace_id) if channel else None,
        company_id=str(channel.company_id) if channel else None,
        added_by=str(datasource.added_by),
        is_active=datasource.is_active,
        is_connected=datasource.is_connected,
        is_processed=datasource.is_processed,
        processing_status=datasource.processing_status,
        error_message=datasource.error_message,
        last_processed_at=datasource.last_processed_at,
        processing_time=datasource.processing_time,
        record_count=datasource.record_count,
        # Pre-existing bug, unrelated to the Aryx integration: these two
        # fields are required (non-Optional) on DatasourceResponse but were
        # never passed here, so this endpoint 500'd on every call before this
        # fix — discovered only because it blocked testing aryx_ingestion_status
        # below. Values match how every other endpoint in this file populates them.
        is_embedding_required=datasource.is_embedding_required,
        embedding_status=datasource.embedding_status,
        created_at=datasource.created_at,
        updated_at=datasource.updated_at,
        # Additive: None for every datasource without an aryx.discovery_id
        # in its metadata — existing (non-Aryx) callers see no change. This
        # is the real "poll by ID" endpoint, so it's the one that reflects
        # LIVE status on every call, not just a snapshot at creation time.
        aryx_ingestion_status=await _aryx_ingestion_status_for(datasource.datasource_metadata)
    )

@router.put("/{datasource_id}", response_model=DatasourceResponse)
async def update_datasource(
    datasource_id: str,
    datasource_data: DatasourceUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> DatasourceResponse:
    """Update a specific datasource"""
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
    
    # Update fields if provided
    if datasource_data.name is not None:
        datasource.name = datasource_data.name
    
    if datasource_data.storage_type is not None:
        datasource.storage_type = datasource_data.storage_type
    
    if datasource_data.provider is not None:
        datasource.provider = datasource_data.provider
    
    if datasource_data.app_type is not None:
        datasource.app_type = datasource_data.app_type
    
    if datasource_data.log_type is not None:
        datasource.log_type = datasource_data.log_type
    
    if datasource_data.config is not None:
        # Update config directly (no vault integration for config updates)
        datasource.config = datasource_data.config.dict()
    
    if datasource_data.datasource_metadata is not None:
        datasource.datasource_metadata = datasource_data.datasource_metadata
    
    if datasource_data.is_active is not None:
        datasource.is_active = datasource_data.is_active
    
    if datasource_data.is_connected is not None:
        datasource.is_connected = datasource_data.is_connected
    
    await db.commit()
    await db.refresh(datasource)
    
    # Get channel for workspace_id and company_id
    channel_stmt = select(Channel).where(Channel.id == datasource.channel_id)
    channel_result = await db.execute(channel_stmt)
    channel = channel_result.scalar_one_or_none()
    
    return DatasourceResponse(
        id=str(datasource.id),
        name=datasource.name,
        filename=datasource.filename,
        storage_type=datasource.storage_type,
        provider=datasource.provider,
        app_type=datasource.app_type,
        config=datasource.config,
        datasource_metadata=sanitize_datasource_metadata(datasource.datasource_metadata),
        file_size=datasource.file_size,
        file_type=datasource.file_type,
        file_url=datasource.file_url,
        channel_id=str(datasource.channel_id),
        workspace_id=str(channel.workspace_id) if channel else None,
        company_id=str(channel.company_id) if channel else None,
        added_by=str(datasource.added_by),
        is_active=datasource.is_active,
        is_connected=datasource.is_connected,
        is_processed=datasource.is_processed,
        processing_status=datasource.processing_status,
        error_message=datasource.error_message,
        last_processed_at=datasource.last_processed_at,
        processing_time=datasource.processing_time,
        record_count=datasource.record_count,
        created_at=datasource.created_at,
        updated_at=datasource.updated_at
    )

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
